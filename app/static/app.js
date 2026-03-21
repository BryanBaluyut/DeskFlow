document.addEventListener('DOMContentLoaded', () => {
    // Auto-resize textareas
    document.querySelectorAll('textarea').forEach(el => {
        el.addEventListener('input', () => {
            el.style.height = 'auto';
            el.style.height = el.scrollHeight + 'px';
        });
    });

    // Bulk actions - select all checkbox
    const selectAll = document.getElementById('select-all');
    const bulkActions = document.getElementById('bulk-actions');
    const bulkForm = document.getElementById('bulk-form');

    if (selectAll) {
        selectAll.addEventListener('change', () => {
            document.querySelectorAll('.ticket-checkbox').forEach(cb => {
                cb.checked = selectAll.checked;
            });
            toggleBulkActions();
        });

        document.querySelectorAll('.ticket-checkbox').forEach(cb => {
            cb.addEventListener('change', toggleBulkActions);
        });
    }

    function toggleBulkActions() {
        const checked = document.querySelectorAll('.ticket-checkbox:checked');
        if (bulkActions) {
            bulkActions.style.display = checked.length > 0 ? 'block' : 'none';
        }
    }

    if (bulkForm) {
        bulkForm.addEventListener('submit', () => {
            const checked = document.querySelectorAll('.ticket-checkbox:checked');
            const ids = Array.from(checked).map(cb => cb.value).join(',');
            document.getElementById('bulk-ticket-ids').value = ids;
        });
    }

    // Text module shortcuts (:: trigger)
    document.querySelectorAll('textarea[name="body"]').forEach(textarea => {
        textarea.addEventListener('input', async (e) => {
            const val = textarea.value;
            const match = val.match(/::(\w+)$/);
            if (match) {
                const keyword = match[1];
                try {
                    const resp = await fetch('/api/v1/text-modules');
                    if (resp.ok) {
                        const data = await resp.json();
                        const module = data.data.find(m => m.keyword === keyword);
                        if (module) {
                            textarea.value = val.replace(`::${keyword}`, module.content);
                        }
                    }
                } catch {}
            }
        });
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Alt+N = new ticket
        if (e.altKey && e.key === 'n') {
            e.preventDefault();
            window.location.href = '/tickets/new';
        }
        // Alt+D = dashboard
        if (e.altKey && e.key === 'd') {
            e.preventDefault();
            window.location.href = '/';
        }
        // Alt+S = search focus
        if (e.altKey && e.key === 's') {
            e.preventDefault();
            const search = document.querySelector('input[name="search"]');
            if (search) search.focus();
        }
    });
});
