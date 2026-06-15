import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

LEDGER_FILE = Path(__file__).parent / "output" / "english_schedule_ledger.json"

def is_weekday_in_regina(schedule_time_utc: str) -> bool:
    if schedule_time_utc.endswith("Z"):
        utc_str = schedule_time_utc[:-1] + "+00:00"
    else:
        utc_str = schedule_time_utc
    dt = datetime.fromisoformat(utc_str).astimezone(ZoneInfo("America/Regina"))
    return dt.weekday() < 5

def guess_slot(channel: str, local_dt: datetime) -> str:
    h, m = local_dt.hour, local_dt.minute
    if channel == "english-challenge":
        if h == 6 and m == 0:
            return "challenge_6am"
        elif h == 10 and m == 0:
            return "challenge_quiz_10am"
    elif channel == "english-quiz":
        if h == 12 and m == 0:
            return "quiz_lunch"
        elif h == 15 and m == 0:
            return "quiz_afternoon"
        elif h == 21 and m == 0:
            return "quiz_night"
    elif channel == "english-shorts":
        if h == 17 and m == 0:
            return "tip_5pm"
    elif channel in ("english", "english-slow"):
        if local_dt.weekday() == 5 and h == 19 and m == 0:
            return "weekend_sat"
        elif local_dt.weekday() == 6 and h == 19 and m == 0:
            return "weekend_sun"
    return "custom"

class ScheduleLedger:
    def __init__(self, filepath=None):
        self.filepath = Path(filepath) if filepath else LEDGER_FILE
        self.timezone_name = "America/Regina"
        self.tz = ZoneInfo(self.timezone_name)
        self.data = self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save(self):
        self.filepath.parent.mkdir(exist_ok=True, parents=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def is_slot_taken(self, date_str: str, slot: str) -> bool:
        for entry in self.data:
            if entry.get("local_date") == date_str and entry.get("slot") == slot:
                return True
        return False

    def get_next_quiz_slot(self, now_dt: datetime):
        slots = [
            ("quiz_lunch", 12, 0),
            ("quiz_afternoon", 15, 0),
            ("quiz_night", 21, 0)
        ]
        current_dt = now_dt.astimezone(self.tz)
        day_offset = 0
        while True:
            check_date = (current_dt + timedelta(days=day_offset)).date()
            date_str = check_date.isoformat()
            
            for slot_name, hour, minute in slots:
                slot_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=self.tz).replace(hour=hour, minute=minute)
                if slot_dt > now_dt + timedelta(minutes=20):
                    if not self.is_slot_taken(date_str, slot_name):
                        return slot_dt, slot_name
            day_offset += 1

    def get_next_shorts_slot(self, now_dt: datetime):
        current_dt = now_dt.astimezone(self.tz)
        day_offset = 0
        while True:
            check_date = (current_dt + timedelta(days=day_offset)).date()
            date_str = check_date.isoformat()
            
            slot_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=self.tz).replace(hour=17, minute=0)
            if slot_dt > now_dt + timedelta(minutes=20):
                if not self.is_slot_taken(date_str, "tip_5pm"):
                    return slot_dt, "tip_5pm"
            day_offset += 1

    def get_next_english_slot(self, now_dt: datetime):
        current_dt = now_dt.astimezone(self.tz)
        day_offset = 0
        while True:
            check_dt = current_dt + timedelta(days=day_offset)
            weekday = check_dt.weekday()
            if weekday == 5: # Saturday
                check_date = check_dt.date()
                date_str = check_date.isoformat()
                slot_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=self.tz).replace(hour=19, minute=0)
                if slot_dt > now_dt + timedelta(minutes=20):
                    if not self.is_slot_taken(date_str, "weekend_sat"):
                        return slot_dt, "weekend_sat"
            elif weekday == 6: # Sunday
                check_date = check_dt.date()
                date_str = check_date.isoformat()
                slot_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=self.tz).replace(hour=19, minute=0)
                if slot_dt > now_dt + timedelta(minutes=20):
                    if not self.is_slot_taken(date_str, "weekend_sun"):
                        return slot_dt, "weekend_sun"
            day_offset += 1

    def get_next_challenge_start_date(self, now_dt: datetime) -> datetime:
        current_dt = now_dt.astimezone(self.tz)
        day_offset = 0
        while True:
            check_date = (current_dt + timedelta(days=day_offset)).date()
            date_str = check_date.isoformat()
            
            slot_dt = datetime.combine(check_date, datetime.min.time(), tzinfo=self.tz).replace(hour=6, minute=0)
            if slot_dt > now_dt + timedelta(minutes=20):
                if not self.is_slot_taken(date_str, "challenge_6am"):
                    return slot_dt
            day_offset += 1

    def get_next_slot(self, channel: str, now_dt: datetime):
        if channel == "english-quiz":
            return self.get_next_quiz_slot(now_dt)
        elif channel == "english-shorts":
            return self.get_next_shorts_slot(now_dt)
        elif channel in ("english", "english-slow"):
            return self.get_next_english_slot(now_dt)
        elif channel == "english-challenge":
            slot_dt = self.get_next_challenge_start_date(now_dt)
            return slot_dt, "challenge_6am"
        else:
            raise ValueError(f"Unknown channel for slot selection: {channel}")

    def record_upload(self, channel: str, schedule_time_utc: str, title: str = None, youtube_id: str = None, slot: str = None):
        if schedule_time_utc.endswith("Z"):
            utc_str = schedule_time_utc[:-1] + "+00:00"
        else:
            utc_str = schedule_time_utc
        dt_utc = datetime.fromisoformat(utc_str)
        dt_local = dt_utc.astimezone(self.tz)
        
        local_date = dt_local.date().isoformat()
        local_time = dt_local.time().isoformat()
        
        if not slot:
            slot = guess_slot(channel, dt_local)
            
        entry = {
            "channel": channel,
            "slot": slot,
            "local_date": local_date,
            "local_time": local_time,
            "timezone": self.timezone_name,
            "schedule_time": schedule_time_utc,
            "title": title,
            "youtube_id": youtube_id
        }
        self.data.append(entry)
        self.save()
        return entry
