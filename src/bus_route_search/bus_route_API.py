import requests
from bs4 import BeautifulSoup

# API 키 설정
bus_api_key = "키"  
local_client_id = "키"
local_client_secret = "키"
geocode_client_id = "키"
geocode_client_secret = "키"

# 01115 정류장에 정차하는 버스 목록을 반환하는 함수
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

# 좌표로부터 반경 내의 정류장 목록을 반환하는 함수
def getNearbyBusStops(lat, lon, radius=500):  # 반경 500m로 수정
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

# 네이버 API로 지명을 기반으로 주소를 찾는 함수
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

# 네이버 API로 주소를 기반으로 좌표를 찾는 함수
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

# 전체 로직을 담당하는 메인 함수
def main():
    # Step 1: 사용자로부터 지명 입력받기
    place = input("목적지를 입력하세요: ")

    # Step 2: 지명의 좌표 조회
    address = get_address_from_place(place)
    if not address:
        print(f"{place}에 대한 주소를 찾을 수 없습니다.")
        return
    
    coordinates = get_coordinates_from_address(address)
    if not coordinates:
        print(f"{place}의 좌표를 찾을 수 없습니다.")
        return
    
    lat, lon = coordinates
    print(f"{place}의 좌표: 위도 {lat}, 경도 {lon}")

    # Step 3: 반경 500m 내의 정류장 조회
    nearby_stops = getNearbyBusStops(lat, lon)
    
    if not nearby_stops:
        print("주변에 정류장이 없습니다.")
        return
    
    print(f"{place} 주변의 정류장 목록:")
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

    # Step 6: 결과 출력
    if buses_to_destination:
        print(f"{place} 주변 정류장으로 가는 01115 정류장의 버스 번호: {', '.join(sorted(buses_to_destination))}")
    else:
        print(f"{place} 주변 정류장으로 가는 01115 정류장의 버스가 없습니다.")

if __name__ == "__main__":
    main()
