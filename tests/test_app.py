"""Exercise the real Streamlit UI without paid AI calls or production data."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import streamlit as st
from streamlit.testing.v1 import AppTest
from persistence import Store, StorageError
from test_persistence import SQLiteAdapter


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.connection_patch = patch(
            "persistence.psycopg.connect",
            side_effect=lambda *args, **kwargs: SQLiteAdapter(self.root / "external.db"),
        )
        self.connection_patch.start()
        self.store = Store("test-only")
        self.store.initialise(self.root / "missing.db")
        self.store.save_document("teacher_profile", {"class_level": "5th Class", "pupil_count": 22})
        self.setup = {
            "timetable_text": "Wednesday PE 11:45",
            "monthly_plan_text": "Maths subtraction. English narrative. Gaeilge oral language.",
            "yearly_plan_text": "5th Class yearly sequence",
        }
        self.store.save_document("planning_setup", self.setup)
        self.store.save_document("current_learning_position", {"Maths": "Addition completed"})
        self.client = Mock()
        self.ai_patch = patch("openai.OpenAI", return_value=self.client)
        self.ai_patch.start()
        st.cache_resource.clear()
        self.app_path = Path(__file__).resolve().parents[1] / "streamlit_app.py"

    def tearDown(self):
        st.cache_resource.clear()
        self.ai_patch.stop()
        self.connection_patch.stop()
        self.temp.cleanup()

    def new_app(self):
        app = AppTest.from_file(str(self.app_path))
        app.secrets["OPENAI_API_KEY"] = "test-not-a-real-key"
        app.secrets["DATABASE_URL"] = "test-only"
        app.run()
        self.assertEqual(len(app.exception), 0)
        return app

    def navigate(self, app, page):
        app.radio[0].set_value(page).run()
        self.assertEqual(len(app.exception), 0)

    def test_adaptive_loop_and_plan_survives_radio_rerun_and_fresh_session(self):
        self.client.responses.create.return_value = SimpleNamespace(output_text="Test plan: subtraction, narrative, Gaeilge.")
        app = self.new_app()
        app.date_input[0].set_value(date(2026, 9, 30)).run()
        app.button[0].click().run()
        original_plan = app.session_state["todays_plan"]
        app.radio[1].set_value("Partially completed").run()
        self.assertEqual(app.session_state["todays_plan"], original_plan)
        self.assertEqual(app.session_state["todays_plan_date"], "2026-09-30")
        updated = {
            "Maths": "Today's subtraction lesson completed",
            "English": "Final narrative activity unfinished",
            "Gaeilge": "Not taught due to assembly; outstanding",
            "SESE": "", "Other": "",
        }
        import json
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps(updated))
        notes = "Maths completed. English final activity unfinished. Gaeilge not taught due to assembly."
        app.text_area[0].set_value(notes)
        app.button[1].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.load_document("current_learning_position"), updated)
        self.assertEqual(self.store.load_progress_history()[0]["notes"], notes)

        # A new Streamlit session hydrates from durable storage.
        fresh = self.new_app()
        self.assertEqual(fresh.session_state["teacher_profile"]["pupil_count"], 22)
        self.assertEqual(fresh.session_state["planning_setup"], self.setup)
        self.assertEqual(fresh.session_state["current_learning_position"], updated)
        self.client.responses.create.return_value = SimpleNamespace(output_text="Next plan continues unfinished English and restores Gaeilge.")
        fresh.date_input[0].set_value(date(2026, 10, 1)).run()
        fresh.button[0].click().run()
        prompt = self.client.responses.create.call_args.kwargs["input"]
        self.assertIn(updated["English"], prompt)
        self.assertIn(updated["Gaeilge"], prompt)
        self.assertIn(notes, prompt)
        self.assertEqual(fresh.session_state["todays_plan_date"], "2026-10-01")

    def test_save_setup_without_reuploads_keeps_all_documents(self):
        app = self.new_app()
        self.navigate(app, "Planning Setup")
        app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.load_document("planning_setup"), self.setup)

    def test_profile_and_current_learning_save_then_new_session(self):
        app = self.new_app()
        self.navigate(app, "Teacher Profile")
        app.text_area[0].set_value("Planet Maths – 5th Class")
        app.button[0].click().run()
        self.navigate(app, "Current Learning")
        app.text_area[0].set_value("Subtraction completed; multiplication next")
        app.button[0].click().run()
        fresh = self.new_app()
        self.assertEqual(fresh.session_state["teacher_profile"]["programmes"], "Planet Maths – 5th Class")
        self.assertEqual(fresh.session_state["current_learning_position"]["Maths"], "Subtraction completed; multiplication next")

    def test_failed_save_does_not_change_saved_or_session_profile(self):
        app = self.new_app()
        self.navigate(app, "Teacher Profile")
        before = dict(app.session_state["teacher_profile"])
        app.text_area[0].set_value("Unsaved change")
        with patch("persistence.Store.save_document", side_effect=StorageError("Database unavailable")):
            app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.success), 0)
        self.assertEqual(app.session_state["teacher_profile"], before)
        self.assertEqual(self.store.load_document("teacher_profile"), before)


if __name__ == "__main__":
    unittest.main()
