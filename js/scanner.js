// ====================================
// СОЗДАНИЕ ИНТЕРФЕЙСА ЧЕРЕЗ JS
// ====================================
function createApp() {
    const app = document.createElement('div');
    app.id = 'app';
    app.innerHTML = `
        <div class="header">
            <span class="logo">📷 PulseQR</span>
            <span class="badge" id="tgStatus">⚪ TG</span>
        </div>

        <div class="video-wrapper">
            <video id="video" playsinline autoplay></video>
            <div class="scan-overlay">
                <div class="scan-frame">
                    <div class="scan-line"></div>
                    <div class="corner top-left"></div>
                    <div class="corner top-right"></div>
                    <div class="corner bottom-left"></div>
                    <div class="corner bottom-right"></div>
                </div>
            </div>
        </div>

        <div class="buttons">
            <button class="btn btn-primary" id="scanBtn">▶️ Сканировать</button>
            <button class="btn btn-secondary" id="stopBtn" style="display: none;">⏹️ Стоп</button>
        </div>

        <div class="status-panel">
            <div class="status-text" id="status">📱 Готов к работе</div>
            <div id="result" class="result-box hidden"></div>
        </div>

        <div class="manual-panel">
            <input type="text" class="manual-input" id="manualInput" placeholder="Вставьте QR‑код">
            <button class="btn btn-secondary" id="manualSend">📤 Отправить</button>
        </div>

        <div class="debug-line" id="debug"></div>
    `;
    document.body.appendChild(app);
}

// ====================================
// ЗАПУСК
// ====================================
createApp();

// ====================================
// TELEGRAM
// ====================================
let tg = null;
try {
    if (window.Telegram?.WebApp) {
        tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();
        document.getElementById('tgStatus').innerText = '✅ TG';
    } else {
        document.getElementById('tgStatus').innerText = '❌ TG';
    }
} catch (e) {
    console.warn(e);
}

// ====================================
// ЭЛЕМЕНТЫ
// ====================================
const video = document.getElementById('video');
const scanBtn = document.getElementById('scanBtn');
const stopBtn = document.getElementById('stopBtn');
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');
const manualInput = document.getElementById('manualInput');
const manualSend = document.getElementById('manualSend');
const debugEl = document.getElementById('debug');

let stream = null;
let scanning = false;
let scanInterval = null;

// ====================================
// ФУНКЦИИ
// ====================================
function debugLog(msg) {
    console.log(msg);
    debugEl.innerText = msg;
}

function setStatus(text, isError = false) {
    statusEl.innerText = text;
    statusEl.style.color = isError ? '#ff8888' : '#aaa';
}

function showResult(text, isError = false) {
    resultEl.innerText = text;
    resultEl.classList.remove('hidden');
    if (isError) {
        resultEl.style.background = '#2a1a1a';
        resultEl.style.borderColor = '#d44';
        resultEl.style.color = '#ffb3b3';
    } else {
        resultEl.style.background = '#0e231a';
        resultEl.style.borderColor = '#2a9eff';
        resultEl.style.color = '#b3ffe0';
    }
    setTimeout(() => resultEl.classList.add('hidden'), 5000);
}

function sendToBot(data) {
    if (!tg) {
        setStatus('❌ Telegram не подключён', true);
        return;
    }
    try {
        tg.sendData(JSON.stringify(data));
        setStatus('✅ Отправлено');
        showResult('✅ QR отправлен в бота');
    } catch (e) {
        setStatus('❌ Ошибка отправки', true);
        showResult('❌ ' + e.message, true);
    }
}

async function startCamera() {
    try {
        setStatus('📷 Запрос камеры...');
        stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment', width: 1280, height: 720 }
        });
        video.srcObject = stream;
        await video.play();
        setStatus('✅ Камера готова');
        scanBtn.disabled = false;
        debugLog('✅ Камера запущена');
    } catch (err) {
        setStatus('❌ Камера недоступна', true);
        showResult('❌ ' + err.message, true);
        debugLog('❌ Ошибка камеры: ' + err.message);
    }
}

function startScan() {
    if (!stream) {
        startCamera().then(() => startScan());
        return;
    }
    scanning = true;
    scanBtn.style.display = 'none';
    stopBtn.style.display = 'block';
    setStatus('🔍 Сканирование...');

    scanInterval = setInterval(() => {
        if (!scanning || !video.videoWidth) return;
        try {
            const canvas = document.createElement('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
            const code = jsQR(imageData.data, canvas.width, canvas.height);
            if (code?.data?.length > 10) {
                debugLog('✅ QR найден');
                stopScan();
                sendToBot({ type: 'qr_scanned', code: code.data, timestamp: Date.now() });
            }
        } catch (e) {}
    }, 250);
}

function stopScan() {
    scanning = false;
    scanBtn.style.display = 'block';
    stopBtn.style.display = 'none';
    setStatus('⏹️ Остановлено');
    clearInterval(scanInterval);
}

manualSend.addEventListener('click', () => {
    const text = manualInput.value.trim();
    if (!text) return showResult('❌ Введите данные', true);
    sendToBot({ type: 'qr_scanned', code: text, timestamp: Date.now() });
    manualInput.value = '';
});

scanBtn.addEventListener('click', startScan);
stopBtn.addEventListener('click', stopScan);

startCamera();

window.addEventListener('beforeunload', () => {
    stream?.getTracks().forEach(t => t.stop());
    clearInterval(scanInterval);
});