import unittest
import tempfile
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

from scripts.schedule_ledger import ScheduleLedger, guess_slot
from scripts.manual_run import is_weekday_in_regina, _upload_video

class TestScheduleLedger(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ledger_file = Path(self.temp_dir.name) / "ledger.json"
        self.ledger = ScheduleLedger(filepath=self.ledger_file)
        self.tz = self.ledger.tz

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_quiz_slots_progression(self):
        # A mock current time: Monday morning 8:00 AM local time
        now_dt = datetime(2026, 6, 15, 8, 0, tzinfo=self.tz)
        
        # 1st run: should select 12 PM today
        dt1, slot1 = self.ledger.get_next_slot("english-quiz", now_dt)
        self.assertEqual(slot1, "quiz_lunch")
        self.assertEqual(dt1.hour, 12)
        self.assertEqual(dt1.date(), now_dt.date())
        
        # Record this run
        self.ledger.record_upload("english-quiz", dt1.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "Quiz 1")
        
        # 2nd run: should select 3 PM today
        dt2, slot2 = self.ledger.get_next_slot("english-quiz", now_dt)
        self.assertEqual(slot2, "quiz_afternoon")
        self.assertEqual(dt2.hour, 15)
        self.assertEqual(dt2.date(), now_dt.date())
        
        # Record this run
        self.ledger.record_upload("english-quiz", dt2.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "Quiz 2")
        
        # 3rd run: should select 9 PM today
        dt3, slot3 = self.ledger.get_next_slot("english-quiz", now_dt)
        self.assertEqual(slot3, "quiz_night")
        self.assertEqual(dt3.hour, 21)
        self.assertEqual(dt3.date(), now_dt.date())
        
        # Record this run
        self.ledger.record_upload("english-quiz", dt3.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "Quiz 3")
        
        # 4th run: should roll to tomorrow 12 PM
        dt4, slot4 = self.ledger.get_next_slot("english-quiz", now_dt)
        self.assertEqual(slot4, "quiz_lunch")
        self.assertEqual(dt4.hour, 12)
        self.assertEqual(dt4.date(), now_dt.date() + timedelta(days=1))

    def test_quiz_slot_time_buffer(self):
        # Current time: 11:45 AM local. 12:00 PM is too close (only 15 mins away).
        # Should select 3:00 PM slot today.
        now_dt = datetime(2026, 6, 15, 11, 45, tzinfo=self.tz)
        dt, slot = self.ledger.get_next_slot("english-quiz", now_dt)
        self.assertEqual(slot, "quiz_afternoon")
        self.assertEqual(dt.hour, 15)

    # skip this test for now since we removed the weekend English slots
    # def test_english_weekend_slots(self):
    #     # A mock current time: Friday 8:00 AM local
    #     now_dt = datetime(2026, 6, 19, 8, 0, tzinfo=self.tz)
        
    #     # 1st run: should select Saturday 7:00 PM
    #     dt1, slot1 = self.ledger.get_next_slot("english", now_dt)
    #     self.assertEqual(slot1, "weekend_sat")
    #     self.assertEqual(dt1.hour, 19)
    #     self.assertEqual(dt1.weekday(), 5) # Saturday
        
    #     self.ledger.record_upload("english", dt1.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "Podcast 1")
        
    #     # 2nd run: should select Sunday 7:00 PM
    #     dt2, slot2 = self.ledger.get_next_slot("english", now_dt)
    #     self.assertEqual(slot2, "weekend_sun")
    #     self.assertEqual(dt2.hour, 19)
    #     self.assertEqual(dt2.weekday(), 6) # Sunday
        
    #     self.ledger.record_upload("english", dt2.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "Podcast 2")
        
    #     # 3rd run: should select next Saturday 7:00 PM
    #     dt3, slot3 = self.ledger.get_next_slot("english", now_dt)
    #     self.assertEqual(slot3, "weekend_sat")
    #     self.assertEqual(dt3.hour, 19)
    #     self.assertEqual(dt3.date(), dt1.date() + timedelta(days=7))

    def test_english_shorts_weekday_notifications(self):
        # Test Monday 5 PM (weekday -> notify True)
        monday_time = "2026-06-15T23:00:00Z" # 5 PM CST is 11 PM UTC
        self.assertTrue(is_weekday_in_regina(monday_time))
        
        # Test Saturday 5 PM (weekend -> notify False)
        saturday_time = "2026-06-20T23:00:00Z"
        self.assertFalse(is_weekday_in_regina(saturday_time))

    def test_english_challenge_start_date_selection(self):
        # Mock current time: Monday morning 8:00 AM local
        now_dt = datetime(2026, 6, 15, 8, 0, tzinfo=self.tz)
        
        # Since it's past 6 AM today, the start date should be tomorrow (Tuesday)
        start_dt = self.ledger.get_next_challenge_start_date(now_dt)
        self.assertEqual(start_dt.date().isoformat(), "2026-06-16")
        
        # Let's record tomorrow's challenge_6am
        self.ledger.record_upload("english-challenge", start_dt.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "Challenge Day 1", slot="challenge_6am")
        
        # Now get next start date again: should be Wednesday
        next_start_dt = self.ledger.get_next_challenge_start_date(now_dt)
        self.assertEqual(next_start_dt.date().isoformat(), "2026-06-17")

    @patch("youtube_uploader.youtube_upload")
    def test_notify_subscribers_plumbing(self, mock_upload):
        mock_upload.return_value = {"youtube_id": "fake_yt_id"}
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video_file = tmp_path / "test_video.mp4"
            video_file.write_bytes(b"dummy content")
            
            with patch("scripts.manual_run.ASSETS_DIR", tmp_path):
                # Write a dummy credentials file so the check passes
                (tmp_path / "yt_credentials_english.json").write_text("{}", encoding="utf-8")
                
                _upload_video(
                    str(video_file),
                    title="Test Title",
                    description="Test Desc",
                    tags=["test"],
                    channel="english",
                    notify_subscribers=False,
                )
            
            mock_upload.assert_called_once()
            self.assertEqual(mock_upload.call_args.kwargs["notify_subscribers"], False)

if __name__ == "__main__":
    unittest.main()
