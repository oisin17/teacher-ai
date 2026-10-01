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
from fixtures import generation_output, sample_plan, outcomes


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
        for month, end in ((9, 30), (10, 31)):
            self.store.save_monthly_plan({"id": str(month), "title": date(2026, month, 1).strftime("%B %Y Monthly Plan"),
                "source_filename": "misleading.docx", "plan_text": self.setup["monthly_plan_text"] + str(month),
                "start_date": f"2026-{month:02}-01", "end_date": f"2026-{month:02}-{end}"}, True)
        october = self.store.select_monthly_plan("2026-10-01")
        self.store.save_period_review(october, "2026-10-01", [], True)
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

    def button(self, app, label):
        return next(item for item in app.button if item.label == label)

    def generated_app(self):
        self.client.responses.create.return_value = SimpleNamespace(output_text=generation_output())
        app = self.new_app()
        app.date_input[0].set_value(date(2026, 9, 30)).run()
        self.button(app, "✨ Generate Today's Plan").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 0)
        return app

    def test_linked_completion_and_manual_controls(self):
        import json
        october = self.store.select_monthly_plan("2026-10-01")
        with self.store._connection() as connection:
            connection.execute("DELETE FROM period_reviews")
        item = {"id": "carry", "period_id": october["id"], "subject": "English", "learning": "Finish final activity", "evidence": "September partial", "created_date": "2026-10-01", "state": "outstanding"}
        self.store.save_period_review(october, "2026-10-01", [item], True)
        output = json.loads(generation_output())
        output["lessons"][1]["carryover_ids"] = ["carry"]
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps(output))
        app = self.new_app()
        app.date_input[0].set_value(date(2026, 10, 1)).run()
        self.button(app, "✨ Generate Today's Plan").click().run()
        self.button(app, "Mark all completed").click().run()
        next(c for c in app.checkbox if c.label.startswith("This carryover is now finished")).check()
        self.button(app, "Save Today's Progress").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.list_carryover()[0]["state"], "completed")
        # A second item can be resolved outside a generated lesson.
        with self.store._connection() as connection:
            second = {**item, "id": "manual", "learning": "Oral practice"}
            connection.execute("INSERT INTO carryover_items (id, item_data) VALUES (%s, %s)", ("manual", json.dumps(second)))
        app.run()
        self.button(app, "Mark complete").click().run()
        self.assertEqual(next(i for i in self.store.list_carryover() if i["id"] == "manual")["state"], "completed")
        self.button(app, "Reopen item").click().run()
        self.assertEqual(next(i for i in self.store.list_carryover() if i["id"] == "manual")["state"], "outstanding")
        self.button(app, "Remove").click().run()
        self.assertEqual(next(i for i in self.store.list_carryover() if i["id"] == "manual")["state"], "removed")
        self.button(app, "Restore item").click().run()
        self.assertEqual(next(i for i in self.store.list_carryover() if i["id"] == "manual")["state"], "outstanding")

    def test_transition_review_suggestions_manual_items_and_no_repeat(self):
        import json
        with self.store._connection() as connection:
            connection.execute("DELETE FROM period_reviews")
        suggestion = {"subject": "English", "learning": "Finish final activity", "evidence": "30 September: unfinished final activity"}
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps({"items": [suggestion]}))
        app = self.new_app()
        app.date_input[0].set_value(date(2026, 10, 1)).run()
        self.assertTrue(self.button(app, "✨ Generate Today's Plan").disabled)
        next(i for i in app.text_area if i.label == "Another carryover item (optional)").set_value("Gaeilge missed lesson")
        self.button(app, "Save carryover and continue").click().run()
        self.assertEqual(len(app.exception), 0)
        items = self.store.list_carryover("2026-10-01")
        self.assertEqual(len(items), 2)
        fresh = self.new_app()
        fresh.date_input[0].set_value(date(2026, 10, 1)).run()
        self.assertFalse(any(b.label == "Nothing to carry over" for b in fresh.button))
        self.assertFalse(self.button(fresh, "✨ Generate Today's Plan").disabled)
        self.store.set_carryover_state(items[0]["id"], "removed")
        self.assertEqual(self.store.list_carryover()[0]["state"], "removed")

    def test_month_boundary_and_missing_month_use_only_confirmed_dates(self):
        self.client.responses.create.return_value = SimpleNamespace(output_text=generation_output())
        app = self.new_app()
        for selected, month in ((date(2026, 9, 30), "September"), (date(2026, 10, 1), "October")):
            app.date_input[0].set_value(selected).run()
            self.assertIn(f"Using {month} 2026 Monthly Plan.", [i.value for i in app.info])
            self.button(app, "✨ Generate Today's Plan").click().run()
            prompt = str(self.client.responses.create.call_args)
            self.assertIn(self.setup["monthly_plan_text"] + str(selected.month), prompt)
            saved = self.store.load_day(selected.isoformat())["plan"]
            self.assertEqual(saved["monthly_plan"]["id"], str(selected.month))
        calls = self.client.responses.create.call_count
        app.date_input[0].set_value(date(2026, 11, 2)).run()
        self.assertTrue(self.button(app, "✨ Generate Today's Plan").disabled)
        self.assertEqual(self.client.responses.create.call_count, calls)

    def test_upload_suggestion_requires_confirmation_and_can_be_corrected(self):
        import io
        from docx import Document
        doc = Document()
        doc.add_paragraph("November 2026 Monthly Plan: English narrative openings")
        upload = io.BytesIO()
        doc.save(upload)
        upload.name = "December_2026.docx"
        real_uploader = st.file_uploader
        def uploader(label, *args, **kwargs):
            if label == "Upload Monthly Plan (PDF or Word)":
                upload.seek(0)
                return upload
            return real_uploader(label, *args, **kwargs)
        with patch("streamlit.file_uploader", side_effect=uploader):
            app = self.new_app()
            self.navigate(app, "Planning Setup")
            self.assertIn("Conflicting date suggestions", " ".join(c.value for c in app.caption))
            for widget in app.date_input:
                if widget.label == "Monthly Plan start date":
                    widget.set_value(date(2026, 11, 1))
                elif widget.label == "Monthly Plan end date":
                    widget.set_value(date(2026, 11, 30))
            self.button(app, "Save confirmed Monthly Plan").click().run()
            self.assertEqual(len(self.store.list_monthly_plans()), 2)
            self.assertTrue(any("Confirm valid" in e.value for e in app.error))
            next(c for c in app.checkbox if c.label.startswith("I confirm")).check()
            self.button(app, "Save confirmed Monthly Plan").click().run()
            self.assertEqual(len(app.exception), 0)
            selected = self.store.select_monthly_plan("2026-11-01")
            self.assertEqual(selected["source_filename"], "December_2026.docx")
            self.assertEqual(selected["start_date"], "2026-11-01")
            self.assertIsNone(self.store.select_monthly_plan("2026-12-01"))
            self.client.responses.create.return_value = SimpleNamespace(output_text=generation_output())
            self.navigate(app, "Today")
            app.date_input[0].set_value(date(2026, 11, 2)).run()
            self.button(app, "Nothing to carry over").click().run()
            self.button(app, "✨ Generate Today's Plan").click().run()
            self.assertEqual(len(app.exception), 0)
            saved = self.store.load_day("2026-11-02")["plan"]
            self.assertEqual(saved["monthly_plan"]["id"], selected["id"])
            self.assertIn("English narrative openings", str(self.client.responses.create.call_args))

    def test_adaptive_loop_and_plan_survives_radio_rerun_and_fresh_session(self):
        app = self.generated_app()
        original_plan = app.session_state["todays_plan"]
        self.assertTrue(all(item.value is None for item in app.radio[1:]))
        self.button(app, "Mark all completed").click().run()
        self.assertTrue(all(item.value == "Completed" for item in app.radio[1:]))
        app.radio[2].set_value("Partially completed").run()
        app.radio[3].set_value("Not taught").run()
        app.text_input[1].set_value("didn't finish final activity")
        app.text_input[2].set_value("not taught because of assembly")
        self.button(app, "Save Today's Progress").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.success), 1)
        self.assertEqual(app.session_state["todays_plan"], original_plan)
        self.assertEqual(app.session_state["todays_plan_date"], "2026-09-30")
        updated = self.store.load_document("current_learning_position")
        self.assertIn("Round five-digit numbers", updated["Maths"])
        self.assertIn("does not establish completion", updated["Maths"])
        self.assertIn("didn't finish final activity", updated["English"])
        self.assertIn("outstanding", updated["Gaeilge"])
        self.assertIn("assembly", updated["Gaeilge"])
        self.assertEqual(len(self.store.load_progress_history()[0]["lessons"]), 3)
        # Saving requires no second AI call: recorded learning commits with progress.
        self.assertEqual(self.client.responses.create.call_count, 1)

        fresh = self.new_app()
        fresh.date_input[0].set_value(date(2026, 9, 30)).run()
        self.assertEqual(fresh.session_state["teacher_profile"]["pupil_count"], 22)
        self.assertEqual(fresh.session_state["planning_setup"], self.setup)
        self.assertEqual(fresh.session_state["current_learning_position"], updated)
        self.assertEqual(fresh.radio[2].value, "Partially completed")
        self.assertEqual(fresh.text_input[2].value, "not taught because of assembly")
        self.assertTrue(self.button(fresh, "✨ Generate Today's Plan").disabled)
        self.assertTrue(any("Narrative openings" in item.value for item in fresh.markdown))
        fresh.date_input[0].set_value(date(2026, 10, 1)).run()
        self.assertEqual(len(fresh.radio), 1)  # old plan cannot receive progress for new date
        self.button(fresh, "✨ Generate Today's Plan").click().run()
        prompt = self.client.responses.create.call_args.kwargs["input"]
        self.assertIn("Use a hook and sensory description", prompt)
        self.assertIn("Ask and answer three questions", prompt)
        self.assertIn("learning_intention", prompt)
        self.assertIn("didn't finish final activity", prompt)
        self.assertEqual(fresh.session_state["todays_plan_date"], "2026-10-01")

    def test_unset_status_cannot_be_saved_and_no_note_is_needed(self):
        app = self.generated_app()
        self.button(app, "Save Today's Progress").click().run()
        self.assertEqual(self.store.load_progress_history(), [])
        self.assertEqual(len(app.warning), 1)
        self.button(app, "Mark all completed").click().run()
        self.button(app, "Save Today's Progress").click().run()
        self.assertEqual(len(self.store.load_progress_history()), 1)
        self.assertIn("Round five-digit numbers", self.store.load_document("current_learning_position")["Maths"])

    def test_mark_all_preserves_notes_and_does_not_save_draft(self):
        app = self.generated_app()
        app.text_input[1].set_value("Keep this teacher correction")
        self.button(app, "Mark all completed").click().run()
        self.assertEqual(app.text_input[1].value, "Keep this teacher correction")
        self.assertEqual(self.store.load_progress_history(), [])
        self.assertTrue(all(item.value == "Completed" for item in app.radio[1:]))

    def test_progress_failure_does_not_update_learning_or_report_success(self):
        app = self.generated_app()
        before = self.store.load_document("current_learning_position")
        self.button(app, "Mark all completed").click().run()
        with patch("persistence.Store.save_lesson_progress", side_effect=StorageError("Database unavailable")):
            self.button(app, "Save Today's Progress").click().run()
        self.assertEqual(len(app.success), 0)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(self.store.load_progress_history(), [])
        self.assertEqual(self.store.load_document("current_learning_position"), before)
        self.assertEqual(app.session_state["current_learning_position"], before)

    def test_history_corrects_individual_lessons_and_preserves_snapshot(self):
        plan = sample_plan()
        self.store.save_day_plan(plan)
        self.store.save_lesson_progress(plan["planning_date"], plan["plan_id"], outcomes(plan))
        app = self.new_app()
        self.navigate(app, "Progress History")
        self.assertEqual(app.radio[2].value, "Partially completed")
        app.radio[2].set_value("Completed").run()
        app.text_input[1].set_value("Finished final activity after lunch")
        self.button(app, "Save Correction").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.success), 1)
        saved = self.store.load_progress_history()[0]
        self.assertEqual(saved["lessons"][1]["status"], "Completed")
        self.assertEqual(saved["lessons"][1]["learning_intention"], plan["lessons"][1]["learning_intention"])
        position = self.store.load_document("current_learning_position")["English"]
        self.assertIn("Finished final activity after lunch", position)
        self.assertNotIn("didn't finish", position)

    def test_legacy_history_remains_correctable(self):
        self.store.save_progress("2026-09-30", "Wednesday", "Partially completed", "English unfinished")
        app = self.new_app()
        app.date_input[0].set_value(date(2026, 9, 30)).run()
        self.assertTrue(self.button(app, "✨ Generate Today's Plan").disabled)
        self.navigate(app, "Progress History")
        import json
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps(
            {"Maths": "", "English": "Final activity completed", "Gaeilge": "", "SESE": "", "Other": ""}))
        app.radio[1].set_value("Completed").run()
        app.text_area[0].set_value("Final activity completed")
        self.button(app, "Save Correction").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.load_progress_history()[0]["status"], "Completed")

    def test_malformed_generation_keeps_previously_saved_plan(self):
        app = self.generated_app()
        before = self.store.load_day("2026-09-30")["plan"]
        self.client.responses.create.return_value = SimpleNamespace(output_text="not json")
        self.button(app, "✨ Generate Today's Plan").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(self.store.load_day("2026-09-30")["plan"], before)

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
