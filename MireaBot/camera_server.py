# camera_server.py
import asyncio
import cv2
import base64
import logging
import numpy as np
from aiohttp import web, WSMsgType
from pyzbar.pyzbar import decode
from datetime import datetime
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Хранилище последних обнаруженных QR-кодов
detected_qrs = {}  # {session_id: {'qr_data': str, 'timestamp': datetime}}


class CameraServer:
    def __init__(self, host='0.0.0.0', port=8080):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.setup_routes()
        self.active_sessions = {}  # {session_id: websocket}

    def setup_routes(self):
        self.app.router.add_get('/', self.index)
        self.app.router.add_get('/stream/{session_id}', self.stream)
        self.app.router.add_get('/ws/{session_id}', self.websocket_handler)
        self.app.router.add_post('/check_qr/{session_id}', self.check_qr)

    async def index(self, request):
        """Главная страница с камерой"""
        session_id = request.query.get('session', '')

        html = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Pulse QR Scanner</title>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
            <style>
                * {{
                    margin: 0;
                    padding: 0;
                    box-sizing: border-box;
                }}

                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: #000;
                    color: #fff;
                    min-height: 100vh;
                    display: flex;
                    flex-direction: column;
                }}

                .container {{
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    padding: 16px;
                }}

                h1 {{
                    font-size: 24px;
                    margin-bottom: 16px;
                    text-align: center;
                    color: #40a7e3;
                }}

                .video-container {{
                    position: relative;
                    width: 100%;
                    max-width: 600px;
                    margin: 0 auto 20px;
                    border-radius: 16px;
                    overflow: hidden;
                    background: #1a1a1a;
                    aspect-ratio: 4/3;
                    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
                }}

                #video {{
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                }}

                .overlay {{
                    position: absolute;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    border: 3px solid #40a7e3;
                    border-radius: 16px;
                    pointer-events: none;
                }}

                .scan-line {{
                    position: absolute;
                    left: 10%;
                    right: 10%;
                    height: 2px;
                    background: #40a7e3;
                    animation: scan 2s linear infinite;
                    box-shadow: 0 0 10px #40a7e3;
                }}

                @keyframes scan {{
                    0% {{ top: 10%; }}
                    50% {{ top: 90%; }}
                    100% {{ top: 10%; }}
                }}

                .status {{
                    background: #1a1a1a;
                    border-radius: 12px;
                    padding: 16px;
                    margin: 16px auto;
                    max-width: 600px;
                    width: 100%;
                    text-align: center;
                    border: 1px solid #333;
                }}

                .qr-result {{
                    background: #1a4d1a;
                    border-radius: 8px;
                    padding: 12px;
                    margin-top: 10px;
                    word-break: break-all;
                    font-size: 14px;
                    border: 1px solid #00ff00;
                    display: none;
                }}

                .qr-result.active {{
                    display: block;
                }}

                button {{
                    background: #40a7e3;
                    color: white;
                    border: none;
                    border-radius: 12px;
                    padding: 16px 24px;
                    font-size: 18px;
                    font-weight: 600;
                    margin: 10px auto;
                    max-width: 300px;
                    width: 100%;
                    cursor: pointer;
                    transition: all 0.2s;
                }}

                button:active {{
                    transform: scale(0.98);
                    opacity: 0.8;
                }}

                button.stop {{
                    background: #ff3b30;
                }}

                .controls {{
                    display: flex;
                    gap: 10px;
                    justify-content: center;
                    flex-wrap: wrap;
                }}

                .info {{
                    color: #888;
                    font-size: 14px;
                    text-align: center;
                    margin-top: 20px;
                }}

                #sessionId {{
                    background: #333;
                    padding: 4px 8px;
                    border-radius: 4px;
                    font-family: monospace;
                    color: #40a7e3;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>📷 Pulse QR Scanner</h1>

                <div class="video-container">
                    <video id="video" playsinline autoplay></video>
                    <div class="overlay"></div>
                    <div class="scan-line"></div>
                </div>

                <div class="status">
                    <div id="statusText">⏳ Запуск камеры...</div>
                    <div id="qrResult" class="qr-result"></div>
                </div>

                <div class="controls">
                    <button onclick="startScanning()" id="startBtn">▶️ Начать сканирование</button>
                    <button onclick="stopScanning()" id="stopBtn" class="stop" style="display: none;">⏹️ Остановить</button>
                </div>

                <div class="info">
                    Сессия: <span id="sessionId">{session_id}</span><br>
                    Наведите камеру на QR-код для автоматического распознавания
                </div>
            </div>

            <script>
                const sessionId = '{session_id}';
                let websocket = null;
                let videoStream = null;
                let isScanning = false;
                let scanInterval = null;

                // Запуск камеры
                async function startCamera() {{
                    try {{
                        const video = document.getElementById('video');

                        // Запрашиваем доступ к камере
                        videoStream = await navigator.mediaDevices.getUserMedia({{
                            video: {{
                                facingMode: 'environment',
                                width: {{ ideal: 1280 }},
                                height: {{ ideal: 720 }}
                            }}
                        }});

                        video.srcObject = videoStream;
                        document.getElementById('statusText').innerHTML = '✅ Камера готова';

                        // Подключаем WebSocket
                        connectWebSocket();

                    }} catch (err) {{
                        document.getElementById('statusText').innerHTML = '❌ Ошибка камеры: ' + err.message;
                        console.error(err);
                    }}
                }}

                // Подключение WebSocket
                function connectWebSocket() {{
                    websocket = new WebSocket(`ws://${{window.location.host}}/ws/${{sessionId}}`);

                    websocket.onopen = function() {{
                        console.log('WebSocket connected');
                    }};

                    websocket.onmessage = function(event) {{
                        const data = JSON.parse(event.data);

                        if (data.type === 'qr_detected') {{
                            showQRResult(data.qr);
                        }}
                    }};

                    websocket.onclose = function() {{
                        console.log('WebSocket disconnected');
                        // Пробуем переподключиться через секунду
                        setTimeout(connectWebSocket, 1000);
                    }};
                }}

                // Захват и отправка кадров
                async function captureAndSend() {{
                    if (!isScanning || !websocket || websocket.readyState !== WebSocket.OPEN) return;

                    const video = document.getElementById('video');

                    // Создаем canvas для захвата кадра
                    const canvas = document.createElement('canvas');
                    canvas.width = video.videoWidth;
                    canvas.height = video.videoHeight;

                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

                    // Конвертируем в base64
                    const base64Image = canvas.toDataURL('image/jpeg', 0.8).split(',')[1];

                    // Отправляем через WebSocket
                    websocket.send(JSON.stringify({{
                        type: 'frame',
                        image: base64Image
                    }}));
                }}

                function showQRResult(qrData) {{
                    const qrResult = document.getElementById('qrResult');
                    qrResult.innerHTML = `✅ QR найден!<br><small>${{qrData.substring(0, 50)}}...</small>`;
                    qrResult.classList.add('active');

                    // Отправляем в бота
                    fetch(`/check_qr/${{sessionId}}`, {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ qr: qrData }})
                    }});

                    // Останавливаем сканирование
                    stopScanning();

                    // Показываем сообщение
                    document.getElementById('statusText').innerHTML = '✅ QR отправлен в бота!';
                }}

                function startScanning() {{
                    isScanning = true;
                    document.getElementById('startBtn').style.display = 'none';
                    document.getElementById('stopBtn').style.display = 'block';
                    document.getElementById('statusText').innerHTML = '🔍 Сканирование...';

                    // Запускаем отправку кадров каждые 500ms
                    scanInterval = setInterval(captureAndSend, 500);
                }}

                function stopScanning() {{
                    isScanning = false;
                    document.getElementById('startBtn').style.display = 'block';
                    document.getElementById('stopBtn').style.display = 'none';
                    document.getElementById('statusText').innerHTML = '⏹️ Сканирование остановлено';

                    if (scanInterval) {{
                        clearInterval(scanInterval);
                    }}
                }}

                // Запускаем камеру при загрузке
                window.onload = startCamera;

                // Остановка камеры при закрытии
                window.onbeforeunload = function() {{
                    if (videoStream) {{
                        videoStream.getTracks().forEach(track => track.stop());
                    }}
                    if (websocket) {{
                        websocket.close();
                    }}
                }};
            </script>
        </body>
        </html>
        '''
        return web.Response(text=html, content_type='text/html')

    async def websocket_handler(self, request):
        """WebSocket для потоковой передачи кадров"""
        session_id = request.match_info['session_id']
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self.active_sessions[session_id] = ws
        logger.info(f"WebSocket connected for session {session_id}")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)

                        if data.get('type') == 'frame':
                            # Декодируем и анализируем кадр
                            image_data = base64.b64decode(data['image'])
                            qr_data = self.detect_qr_from_bytes(image_data)

                            if qr_data:
                                # Сохраняем найденный QR
                                detected_qrs[session_id] = {
                                    'qr_data': qr_data,
                                    'timestamp': datetime.now()
                                }

                                # Отправляем клиенту
                                await ws.send_json({
                                    'type': 'qr_detected',
                                    'qr': qr_data
                                })

                    except Exception as e:
                        logger.error(f"Error processing frame: {e}")

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
            logger.info(f"WebSocket closed for session {session_id}")

        return ws

    def detect_qr_from_bytes(self, image_bytes):
        """Детектит QR-код из байтов изображения"""
        try:
            # Конвертируем байты в numpy array
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                return None

            # Декодируем QR
            decoded_objects = decode(img)

            for obj in decoded_objects:
                if obj.type == 'QRCODE':
                    return obj.data.decode('utf-8')

            return None

        except Exception as e:
            logger.error(f"QR detection error: {e}")
            return None

    async def stream(self, request):
        """HTTP endpoint для видео потока"""
        session_id = request.match_info['session_id']

        # Перенаправляем на главную с session_id
        raise web.HTTPFound(f'/?session={session_id}')

    async def check_qr(self, request):
        """Проверка наличия QR для сессии"""
        session_id = request.match_info['session_id']

        try:
            data = await request.json()
            qr_data = data.get('qr')

            if qr_data:
                # Здесь можно отправить уведомление боту
                logger.info(f"QR detected for session {session_id}: {qr_data[:50]}...")

                # Сохраняем для бота
                detected_qrs[session_id] = {
                    'qr_data': qr_data,
                    'timestamp': datetime.now()
                }

                return web.json_response({'status': 'ok'})

        except Exception as e:
            logger.error(f"Check QR error: {e}")

        return web.json_response({'status': 'error'}, status=400)

    def get_qr_for_session(self, session_id):
        """Получить QR для сессии (для бота)"""
        if session_id in detected_qrs:
            qr_info = detected_qrs[session_id]
            # Удаляем после получения
            del detected_qrs[session_id]
            return qr_info['qr_data']
        return None

    async def start(self):
        """Запуск сервера"""
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info(f"Camera server started on http://{self.host}:{self.port}")
        return runner


# Глобальный экземпляр сервера
camera_server = CameraServer()