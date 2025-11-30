import logging
import io
from collections import deque

class BufferedLogger(logging.Handler):
    """
    로그를 메모리에 버퍼링하는 로깅 핸들러.
    최대 max_lines 만큼의 로그를 저장합니다.
    """
    def __init__(self, max_lines=1000):
        super().__init__()
        self.buffer = deque(maxlen=max_lines)
        self.formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
        except Exception:
            self.handleError(record)

    def get_logs(self):
        """버퍼에 저장된 모든 로그를 문자열로 반환합니다."""
        return "\n".join(self.buffer)

    def clear(self):
        """버퍼를 비웁니다."""
        self.buffer.clear()

# 전역 로거 설정
buffered_handler = BufferedLogger(max_lines=2000)

def setup_logger():
    """로거 초기화 및 핸들러 추가"""
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO) # 기본 레벨 INFO

    # 콘솔 핸들러 (기본 출력)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    root_logger.addHandler(console_handler)

    # 버퍼 핸들러 (메모리 저장)
    root_logger.addHandler(buffered_handler)

    return buffered_handler

def set_debug_mode(enabled: bool):
    """디버그 모드 활성화/비활성화 (로그 레벨 변경)"""
    root_logger = logging.getLogger()
    if enabled:
        root_logger.setLevel(logging.DEBUG)
        logging.info("🔧 DEBUG MODE ENABLED")
    else:
        root_logger.setLevel(logging.INFO)
        logging.info("🔧 DEBUG MODE DISABLED")
