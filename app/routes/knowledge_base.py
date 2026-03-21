import bleach
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_user, require_agent
from app.database import get_db
from app.models import KBCategory, KBArticle, ArticleVisibility, User, UserRole

router = APIRouter(prefix="/knowledge-base", tags=["knowledge_base"])

ALLOWED_TAGS = ["p", "br", "b", "i", "u", "a", "ul", "ol", "li", "pre", "code", "strong", "em",
                "blockquote", "h1", "h2", "h3", "h4", "img", "table", "thead", "tbody", "tr", "th", "td"]


@router.get("/", response_class=HTMLResponse)
async def kb_home(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    categories = (await db.execute(
        select(KBCategory).where(KBCategory.parent_id.is_(None))
        .options(selectinload(KBCategory.children))
        .order_by(KBCategory.position)
    )).scalars().all()

    return request.app.state.templates.TemplateResponse("kb/index.html", {
        "request": request, "user": user, "categories": categories,
    })


@router.get("/category/{category_id}", response_class=HTMLResponse)
async def kb_category(
    request: Request, category_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    category = await db.get(KBCategory, category_id, options=[
        selectinload(KBCategory.children),
        selectinload(KBCategory.articles).selectinload(KBArticle.author),
    ])
    if not category:
        raise HTTPException(404)

    # Filter articles based on role
    if user.role == UserRole.customer:
        articles = [a for a in category.articles if a.visibility == ArticleVisibility.public]
    elif user.role in (UserRole.agent, UserRole.admin):
        articles = category.articles
    else:
        articles = [a for a in category.articles if a.visibility != ArticleVisibility.draft]

    return request.app.state.templates.TemplateResponse("kb/category.html", {
        "request": request, "user": user, "category": category,
        "articles": articles,
    })


@router.get("/article/{article_id}", response_class=HTMLResponse)
async def kb_article(
    request: Request, article_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    article = await db.get(KBArticle, article_id, options=[
        selectinload(KBArticle.author), selectinload(KBArticle.category),
    ])
    if not article:
        raise HTTPException(404)
    if user.role == UserRole.customer and article.visibility != ArticleVisibility.public:
        raise HTTPException(403)

    return request.app.state.templates.TemplateResponse("kb/article.html", {
        "request": request, "user": user, "article": article,
    })


@router.get("/search", response_class=HTMLResponse)
async def kb_search(
    request: Request, q: str = "",
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user),
):
    articles = []
    if q:
        query = select(KBArticle).options(
            selectinload(KBArticle.author), selectinload(KBArticle.category),
        ).where(
            KBArticle.title.ilike(f"%{q}%") | KBArticle.body_html.ilike(f"%{q}%")
        )
        if user.role == UserRole.customer:
            query = query.where(KBArticle.visibility == ArticleVisibility.public)
        articles = (await db.execute(query.limit(50))).scalars().all()

    return request.app.state.templates.TemplateResponse("kb/search.html", {
        "request": request, "user": user, "articles": articles, "query": q,
    })


# --- Agent/Admin management ---

@router.get("/manage", response_class=HTMLResponse)
async def kb_manage(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(require_agent)):
    categories = (await db.execute(
        select(KBCategory).options(selectinload(KBCategory.children), selectinload(KBCategory.articles))
        .order_by(KBCategory.position)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse("kb/manage.html", {
        "request": request, "user": user, "categories": categories,
        "visibilities": list(ArticleVisibility),
    })


@router.post("/categories")
async def create_category(
    name: str = Form(...), parent_id: int | None = Form(None),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    cat = KBCategory(name=name, parent_id=parent_id)
    db.add(cat)
    await db.commit()
    return RedirectResponse(url="/knowledge-base/manage", status_code=302)


@router.post("/categories/{cat_id}/delete")
async def delete_category(cat_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_agent)):
    cat = await db.get(KBCategory, cat_id)
    if cat:
        await db.delete(cat)
        await db.commit()
    return RedirectResponse(url="/knowledge-base/manage", status_code=302)


@router.get("/articles/new", response_class=HTMLResponse)
async def new_article_form(
    request: Request, category_id: int = 0,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    categories = (await db.execute(select(KBCategory).order_by(KBCategory.name))).scalars().all()
    return request.app.state.templates.TemplateResponse("kb/article_edit.html", {
        "request": request, "user": user, "article": None,
        "categories": categories, "visibilities": list(ArticleVisibility),
        "selected_category_id": category_id,
    })


@router.post("/articles")
async def create_article(
    title: str = Form(...), body_html: str = Form(""),
    category_id: int = Form(...), visibility: str = Form("draft"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    article = KBArticle(
        title=title, body_html=bleach.clean(body_html, tags=ALLOWED_TAGS, strip=True),
        category_id=category_id, visibility=ArticleVisibility(visibility),
        author_id=user.id,
    )
    db.add(article)
    await db.commit()
    await db.refresh(article)
    return RedirectResponse(url=f"/knowledge-base/article/{article.id}", status_code=302)


@router.get("/articles/{article_id}/edit", response_class=HTMLResponse)
async def edit_article_form(
    request: Request, article_id: int,
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    article = await db.get(KBArticle, article_id)
    if not article:
        raise HTTPException(404)
    categories = (await db.execute(select(KBCategory).order_by(KBCategory.name))).scalars().all()
    return request.app.state.templates.TemplateResponse("kb/article_edit.html", {
        "request": request, "user": user, "article": article,
        "categories": categories, "visibilities": list(ArticleVisibility),
        "selected_category_id": article.category_id,
    })


@router.post("/articles/{article_id}/edit")
async def update_article(
    article_id: int,
    title: str = Form(...), body_html: str = Form(""),
    category_id: int = Form(...), visibility: str = Form("draft"),
    db: AsyncSession = Depends(get_db), user: User = Depends(require_agent),
):
    article = await db.get(KBArticle, article_id)
    if not article:
        raise HTTPException(404)
    article.title = title
    article.body_html = bleach.clean(body_html, tags=ALLOWED_TAGS, strip=True)
    article.category_id = category_id
    article.visibility = ArticleVisibility(visibility)
    await db.commit()
    return RedirectResponse(url=f"/knowledge-base/article/{article_id}", status_code=302)


@router.post("/articles/{article_id}/delete")
async def delete_article(article_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(require_agent)):
    article = await db.get(KBArticle, article_id)
    if article:
        await db.delete(article)
        await db.commit()
    return RedirectResponse(url="/knowledge-base/manage", status_code=302)


# --- Public knowledge base (no auth required for public articles) ---
public_router = APIRouter(prefix="/help", tags=["public_kb"])


@public_router.get("/", response_class=HTMLResponse)
async def public_kb_home(request: Request, db: AsyncSession = Depends(get_db)):
    categories = (await db.execute(
        select(KBCategory).where(KBCategory.parent_id.is_(None))
        .options(selectinload(KBCategory.children))
        .order_by(KBCategory.position)
    )).scalars().all()
    return request.app.state.templates.TemplateResponse("kb/public_index.html", {
        "request": request, "categories": categories,
    })


@public_router.get("/article/{article_id}", response_class=HTMLResponse)
async def public_kb_article(request: Request, article_id: int, db: AsyncSession = Depends(get_db)):
    article = await db.get(KBArticle, article_id, options=[
        selectinload(KBArticle.author), selectinload(KBArticle.category),
    ])
    if not article or article.visibility != ArticleVisibility.public:
        raise HTTPException(404)
    return request.app.state.templates.TemplateResponse("kb/public_article.html", {
        "request": request, "article": article,
    })


@public_router.get("/search", response_class=HTMLResponse)
async def public_kb_search(request: Request, q: str = "", db: AsyncSession = Depends(get_db)):
    articles = []
    if q:
        articles = (await db.execute(
            select(KBArticle).options(selectinload(KBArticle.category))
            .where(
                KBArticle.visibility == ArticleVisibility.public,
                KBArticle.title.ilike(f"%{q}%") | KBArticle.body_html.ilike(f"%{q}%"),
            ).limit(50)
        )).scalars().all()
    return request.app.state.templates.TemplateResponse("kb/public_search.html", {
        "request": request, "articles": articles, "query": q,
    })
