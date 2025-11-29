import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 디스코드 봇 토큰
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 디스코드 봇 토큰
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# 구글 서비스 계정 키 파일 경로
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE', 'service_account.json')

# 구글 스프레드시트 ID (환경변수에서 로드하거나 직접 입력)
SPREADSHEET_ID_A = os.getenv('SPREADSHEET_ID_A') # 캐릭터 스탯 정리표
SPREADSHEET_ID_B = os.getenv('SPREADSHEET_ID_B') # 정보 및 조사 데이터
SPREADSHEET_ID_C = os.getenv('SPREADSHEET_ID_C') # 정보 및 조사 데이터

# 봇 커맨드 접두사
COMMAND_PREFIX = '/'

# 관리자 ID 목록 (필요시)
ADMIN_IDS = [1090546247770832910]

# 조사 공지 채널 ID
NOTICE_CHANNEL_ID = 1443997512733298990
