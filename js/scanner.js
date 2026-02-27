// Telegram WebApp
let tg = null;
try {
    if (window.Telegram?.WebApp) {
        tg = window.Telegram.WebApp;
        tg.ready();
        tg.expand();
        document.getElementById('tgStatus').innerText = '✅ Telegram';
    } else {
        document.getElementById('tgStatus').innerText = '❌ Telegram';
    }
} catch (e) {
    console.warn('Telegram init error', e);
}

// Элементы
const video = document.getElementById('video');
const scanBtn = document.getElementById('scanBtn');
const stopBtn = document.getElementById('stopBtn');
const statusEl = document.getElementById('status');
const resultEl = document.getElementById('result');
const manualInput = document.getElementById('manualInput');
const manualSend = document.getElementById('manualSend');

let stream = null;
let scanning = false;
let scanInterval = null;

// Логирование статуса
function setStatus(text, isError = false) {
    statusEl.innerText = text;
    statusEl.style.color = isError ? '#ff6b6b' : '#aaa';
}

// Показать результат
function showResult(text, isError = false) {
    resultEl.innerText = text;
    resultEl.classList.remove('hidden');
    if (isError) {
        resultEl.style.background = '#2a1a1a';
        resultEl.style.borderColor = '#d32f2f';
        resultEl.style.color = '#ffb3b3';
    } else {
        resultEl.style.background = '#0e2a1a';
        resultEl.style.borderColor = '#2e7d5e';
        resultEl.style.color = '#b5ffd0';
    }
    setTimeout(() => resultEl.classList.add('hidden'), 5000);
}

// Отправка данных в бота
function sendToBot(data) {
    if (!tg) {
        setStatus('❌ Telegram не подключён', true);
        return;
    }
    try {
        tg.sendData(JSON.stringify(data));
        setStatus('✅ Данные отправлены');
        showResult('✅ QR отправлен в бота');
    } catch (e) {
        setStatus('❌ Ошибка отправки', true);
        showResult('❌ ' + e.message, true);
    }
}

// Камера
async function startCamera() {
    try {
        setStatus('⏳ Запрос камеры...');
        stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'environment', width: 1280, height: 720 }
        });
        video.srcObject = stream;
        await video.play();
        setStatus('✅ Камера готова');
        scanBtn.disabled = false;
    } catch (err) {
        setStatus('❌ Камера недоступна', true);
        showResult('❌ ' + err.message, true);
    }
}

// Сканирование
function startScan() {
    if (!stream) return startCamera().then(startScan);
    scanning = true;
    scanBtn.style.display = 'none';
    stopBtn.style.display = 'block';
    setStatus('🔍 Сканирование...');

    scanInterval = setInterval(() => {
        if (!scanning || !video.videoWidth) return;
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0);
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(imageData.data, canvas.width, canvas.height);
        if (code?.data?.length > 10) {
            stopScan();
            sendToBot({ type: 'qr_scanned', code: code.data, timestamp: Date.now() });
        }
    }, 300);
}

function stopScan() {
    scanning = false;
    scanBtn.style.display = 'block';
    stopBtn.style.display = 'none';
    setStatus('⏹️ Сканирование остановлено');
    clearInterval(scanInterval);
}

// Ручной ввод
manualSend.addEventListener('click', () => {
    const text = manualInput.value.trim();
    if (!text) return showResult('❌ Введите данные', true);
    sendToBot({ type: 'qr_scanned', code: text, timestamp: Date.now() });
    manualInput.value = '';
});

// Инициализация
startCamera();

// Очистка
window.addEventListener('beforeunload', () => {
    stream?.getTracks().forEach(t => t.stop());
    clearInterval(scanInterval);
});