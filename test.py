import RPi.GPIO as GPIO
import time
import pygame
import queue
import re
import sys
from google.cloud import speech
import pyaudio
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import SVC
from konlpy.tag import Okt
import requests
from bs4 import BeautifulSoup
from gtts import gTTS  # TTS 라이브러리 임포트
import os  # 파일 시스템을 위한 라이브러리 임포트
from dotenv import load_dotenv # dotenv 라이브러리 임포트

# .env 파일 로드
load_dotenv()

# 환경변수로부터 API 키 설정
bus_api_key = os.getenv("BUS_API_KEY")
local_client_id = os.getenv("LOCAL_CLIENT_ID")
local_client_secret = os.getenv("LOCAL_CLIENT_SECRET")
geocode_client_id = os.getenv("GEOCODE_CLIENT_ID")
geocode_client_secret = os.getenv("GEOCODE_CLIENT_SECRET")

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms

continue_listening = True

class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""
    def __init__(self, rate=RATE, chunk=CHUNK):
        self._rate = rate
        self._chunk = chunk
        self._buff = queue.Queue()
        self.closed = True

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )
        self.closed = False
        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):
        while not self.closed:
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break
            yield b"".join(data)

def listen_print_loop(responses, intent_detector):
    global continue_listening
    num_chars_printed = 0
    for response in responses:
        if not continue_listening:
            break
        if not response.results:
            continue
        result = response.results[0]
        if not result.alternatives:
            continue
        transcript = result.alternatives[0].transcript
        overwrite_chars = " " * (num_chars_printed - len(transcript))

        if not result.is_final:
            sys.stdout.write(transcript + overwrite_chars + "\r")
            sys.stdout.flush()
            num_chars_printed = len(transcript)
        else:
            print(transcript + overwrite_chars)
            intent, destination = intent_detector.recognize_intent_and_destination(transcript)
            print(f"의도: {intent}, 목적지: {destination}")
            if intent == "버스 번호 검색" and destination:
                process_destination(destination)
                continue_listening = False
                break
            num_chars_printed = 0

def play_prompt():
    print("Playing prompt...")
    pygame.mixer.init()
    pygame.mixer.music.load("voice.mp3")  # 파일 경로에 맞게 수정
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        time.sleep(1)

def record_audio(intent_detector):
    print("Recording audio...")
    language_code = "ko-KR"  # 한국어
    client = speech.SpeechClient()
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        language_code=language_code,
    )
    streaming_config = speech.StreamingRecognitionConfig(
        config=config, interim_results=True
    )
    
    with MicrophoneStream(RATE, CHUNK) as stream:
        audio_generator = stream.generator()
        requests = (
            speech.StreamingRecognizeRequest(audio_content=content)
            for content in audio_generator
        )
        responses = client.streaming_recognize(streaming_config, requests)
        listen_print_loop(responses, intent_detector)
    
    # 명시적으로 gRPC 연결을 종료
    client.transport.channel.close()  # gRPC 채널 종료

class SimpleIntentDetector:
    def __init__(self):
        self.okt = Okt()
        self.vectorizer = TfidfVectorizer()
        self.model = SVC(probability=True)

        # 샘플 데이터셋
        self.train_texts = [
            "용산 가려면 몇 번 타야돼?",
            "강남역 가는 노선 알려줘",
            "경복궁 가고 싶어",
            "서울역 갈래",
            "집에 가고 싶어",
            "구로디지털단지역 가려면 몇번 버스 타야해?"
        ]
        self.train_labels = [
            "버스 번호 검색",
            "버스 번호 검색",
            "버스 번호 검색",
            "버스 번호 검색",
            "노선 없음",
            "버스 번호 검색"
        ]

        self.train()

    def preprocess_text(self, text):
        tokens = self.okt.nouns(text)
        return ' '.join(tokens)

    def train(self):
        processed_texts = [self.preprocess_text(text) for text in self.train_texts]
        X_train = self.vectorizer.fit_transform(processed_texts)
        self.model.fit(X_train, self.train_labels)

    def extract_destination(self, text):
        tokens = self.okt.pos(text)
        destination = None
        for token, pos in tokens:
            if pos == 'Noun' and '역' in token:
                destination = token
                break
            if pos == 'Noun' and len(token) > 1:
                destination = token

        return destination

    def recognize_intent_and_destination(self, text):
        destination = self.extract_destination(text)
        if destination:
            intent = '버스 번호 검색'
        else:
            intent = self.recognize_intent(text)
            if intent == '버스 번호 검색':
                intent = '노선 없음'

        return intent, destination

    def recognize_intent(self, text):
        processed_text = self.preprocess_text(text)
        X_input = self.vectorizer.transform([processed_text])
        intent = self.model.predict(X_input)[0]
        return intent

# 버스 관련 함수들
def getBusnmByStID(ars_id):
    url = "http://ws.bus.go.kr/api/rest/stationinfo/getRouteByStation"
    queryParams = f"?ServiceKey={bus_api_key}&arsId={ars_id}"

    xml = requests.get(url + queryParams).text
    root = BeautifulSoup(xml, 'xml')
    res = root.select('itemList')

    bus_list = []
    for bus in res:
        bus_nm = bus.find('busRouteNm').text
        bus_list.append(bus_nm)
        
    return bus_list

def getNearbyBusStops(lat, lon, radius=500):
    url = "http://ws.bus.go.kr/api/rest/stationinfo/getStationByPos"
    queryParams = f"?ServiceKey={bus_api_key}&tmX={lon}&tmY={lat}&radius={radius}"
    
    xml = requests.get(url + queryParams).text
    root = BeautifulSoup(xml, 'xml')
    station_list = root.select('itemList')

    nearby_stops = []
    for station in station_list:
        ars_id = station.find('arsId').text
        station_nm = station.find('stationNm').text
        nearby_stops.append({'arsId': ars_id, 'stationNm': station_nm})

    return nearby_stops

def get_address_from_place(query):
    url = "https://openapi.naver.com/v1/search/local.json"
    headers = {
        "X-Naver-Client-Id": local_client_id,
        "X-Naver-Client-Secret": local_client_secret
    }
    params = {"query": query, "display": 1}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        if data['items']:
            return data['items'][0]['roadAddress'] or data['items'][0]['address']
    return None

def get_coordinates_from_address(address):
    url = "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": geocode_client_id,
        "X-NCP-APIGW-API-KEY": geocode_client_secret
    }
    params = {"query": address}
    
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        if data['addresses']:
            latitude = float(data['addresses'][0]['y'])
            longitude = float(data['addresses'][0]['x'])
            return latitude, longitude
    return None

def process_destination(destination):
    print(f"목적지: {destination}")

    # Step 2: 지명의 좌표 조회
    address = get_address_from_place(destination)
    if not address:
        print(f"{destination}에 대한 주소를 찾을 수 없습니다.")
        return
    
    coordinates = get_coordinates_from_address(address)
    if not coordinates:
        print(f"{destination}의 좌표를 찾을 수 없습니다.")
        return
    
    lat, lon = coordinates
    print(f"{destination}의 좌표: 위도 {lat}, 경도 {lon}")

    # Step 3: 반경 500m 내의 정류장 조회
    nearby_stops = getNearbyBusStops(lat, lon)
    
    if not nearby_stops:
        print("주변에 정류장이 없습니다.")
        return
    
    print(f"{destination} 주변의 정류장 목록:")
    for stop in nearby_stops:
        print(f"정류장명: {stop['stationNm']}, arsId: {stop['arsId']}")

    # Step 4: 01115 정류장에 정차하는 버스 목록 조회
    ars_id_fixed = "01115"
    buses_at_01115 = getBusnmByStID(ars_id_fixed)
    
    if not buses_at_01115:
        print(f"정류장ID {ars_id_fixed}에서 정차하는 버스가 없습니다.")
        return
    
    print(f"정류장ID {ars_id_fixed}에서 정차하는 버스 목록: {buses_at_01115}")

    # Step 5: 01115 정류장의 버스가 주변 정류장에도 있는지 확인
    buses_to_destination = set()  # 중복을 방지하기 위해 set 사용
    for stop in nearby_stops:
        stop_buses = getBusnmByStID(stop['arsId'])
        common_buses = set(buses_at_01115).intersection(set(stop_buses))
        
        if common_buses:
            buses_to_destination.update(common_buses)

    # Step 6: 결과 출력 및 TTS 기능 추가
    if buses_to_destination:
        bus_numbers = ', '.join(sorted(buses_to_destination))
        print(f"{destination} 주변 정류장으로 가는 버스 번호는 {bus_numbers}")
        
        # TTS 기능 추가
        tts_text = f"{destination} 주변 정류장으로 가는 버스는 {bus_numbers}입니다."
        tts = gTTS(text=tts_text, lang='ko')
        tts_file = "tts.mp3"
        tts.save(tts_file)

        # TTS 음성 재생
        pygame.mixer.init()
        pygame.mixer.music.load(tts_file)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(1)

# GPIO 설정
button_pin = 15

GPIO.setwarnings(False)
GPIO.setmode(GPIO.BCM)
GPIO.setup(button_pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# IntentDetector 초기화
intent_detector = SimpleIntentDetector()

# 버튼 콜백 함수
def button_callback(channel):
    play_prompt()
    record_audio(intent_detector)

# Event 방식으로 핀의 Rising 신호를 감지 -> button_callback 함수 실행
GPIO.add_event_detect(button_pin, GPIO.RISING, callback=button_callback, bouncetime=300)

try:
    print("버튼을 누르면 음성 인식이 시작됩니다...")
    # 한 번의 작업 후 종료
    while continue_listening:
        time.sleep(0.1)
finally:
    GPIO.cleanup()
