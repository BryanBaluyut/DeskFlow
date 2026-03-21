// DeskFlow Chat Widget - Embed with:
// <script src="https://your-deskflow/static/widget.js" data-form-id="1"></script>
(function() {
    const script = document.currentScript;
    const baseUrl = script.src.replace('/static/widget.js', '');

    const container = document.createElement('div');
    container.id = 'deskflow-widget';
    container.innerHTML = `
        <style>
            #deskflow-widget-btn { position: fixed; bottom: 20px; right: 20px; width: 56px; height: 56px; border-radius: 50%; background: #2563eb; color: white; border: none; font-size: 24px; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.15); z-index: 9999; }
            #deskflow-widget-frame { position: fixed; bottom: 90px; right: 20px; width: 380px; height: 500px; border: none; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.12); z-index: 9999; display: none; }
        </style>
        <button id="deskflow-widget-btn" onclick="document.getElementById('deskflow-widget-frame').style.display = document.getElementById('deskflow-widget-frame').style.display === 'none' ? 'block' : 'none'">&#128172;</button>
        <iframe id="deskflow-widget-frame" src="${baseUrl}/widget/chat"></iframe>
    `;
    document.body.appendChild(container);
})();
