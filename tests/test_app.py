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
        def model_response(**kwargs):
            if kwargs['text']['format']['name'] == 'planning_quality_review':
                import json
                from planning_quality import CATEGORIES
                def unwrap(value):
                    if isinstance(value,dict):
                        if set(value)=={'evidence_id','text'}:return value['text']
                        if set(value)=={'passages'}:return ''.join(unwrap(v) for v in value['passages'])
                        return {k:unwrap(v) for k,v in value.items()}
                    if isinstance(value,list):return [unwrap(v) for v in value]
                    return value
                packet=unwrap(json.loads(kwargs['input'].split('SOURCE-REFERENCED PACKET:')[1].split('\n',1)[1]))
                context=packet['context'];plan=packet['candidate']
                linked={id for l in plan['lessons'] for id in l.get('carryover_ids',[])}
                return SimpleNamespace(output_text=json.dumps(dict(checked_categories=list(CATEGORIES),findings=[],carryover_decisions=[dict(id=c['id'],decision='addressed' if c['id'] in linked else 'deferred',reason='Appropriate next subject slot after fixed routines') for c in context['carryover'] if c['state']=='outstanding'])))
            return self.client.responses.create.return_value
        self.client.responses.create.side_effect=model_response
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

    def test_rubric_bad_candidate_keeps_previous_and_all_learning(self):
        import json
        previous=sample_plan('2026-10-01');self.store.save_day_plan(previous)
        before=self.store.export_backup()
        output=json.loads(generation_output());output['lessons'][0]['phases'][0]['minutes']=90
        output['overview']=output['overview'].replace('09:30–10:00','09:30–10:10')
        self.client.responses.create.return_value=SimpleNamespace(output_text=json.dumps(output))
        app=self.new_app();app.date_input[0].set_value(date(2026,10,1)).run()
        self.button(app, "✨ Generate Today's Plan").click().run()
        self.assertEqual(len(app.error),1)
        self.assertEqual(app.session_state['last_planning_check']['state'],'Blocked')
        self.assertEqual(self.store.export_backup(),before)
        self.assertEqual(self.client.responses.create.call_count,2) # generation + one repair; no review before code passes

    def test_read_only_browser_probe_does_not_save_candidate(self):
        self.store.save_document('teacher_profile',{'class_level':'5th Class','recurring_arrangements':'Daily\n11:00–11:15 Yard'})
        self.store.save_day_plan(sample_plan('2026-10-01'))
        self.client.responses.create.return_value=SimpleNamespace(output_text=generation_output())
        app=self.new_app();app.query_params['rubric_probe']='read-only';app.date_input[0].set_value(date(2026,10,1)).run()
        before=self.store.export_backup()
        self.button(app,'Test conflicting candidate without saving').click().run()
        self.assertEqual(len(app.exception),0)
        self.assertEqual(self.store.export_backup(),before)
        self.assertTrue(any('Previous saved plan unchanged: True' in m.value for m in app.markdown))

    def test_item_review_extract_save_merge_and_restore(self):
        import json
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps({'items': [dict(subject='History', description='Activity one', type='discrete', source_index=0), dict(subject='History', description='Activity two', type='broad', source_index=0)]}))
        app = self.new_app()
        self.navigate(app, 'Planning Setup')
        next(i for i in app.selectbox if i.label == 'Monthly Plan to add or edit').set_value('9').run()
        self.button(app, 'Suggest learning items').click().run()
        self.assertEqual(len(app.exception), 0)
        self.button(app, 'Save learning items').click().run()
        self.assertEqual(len(app.exception), 0)
        saved = self.store.list_learning_items('9')
        self.assertEqual(len(saved), 2)
        next(i for i in app.multiselect if i.label == 'Merge duplicate / overlapping items').set_value([i['id'] for i in saved])
        next(i for i in app.text_input if i.label == 'Merged item description').set_value('Merged activity')
        self.button(app, 'Save learning items').click().run()
        self.assertEqual(len(app.exception), 0)
        saved = self.store.list_learning_items('9')
        self.assertEqual(sum(not i['archived'] for i in saved), 1)
        self.assertEqual(next(i for i in saved if not i['archived'])['type'], 'broad')

    def test_item_suggestions_remain_drafts_and_explicit_completion_required(self):
        import json
        from monthly_learning import fingerprint
        monthly = self.store.select_monthly_plan('2026-09-30')
        item = dict(id='test-item', monthly_plan_id='9', subject='English', description='Opening paragraph', source='English narrative.', fingerprint=fingerprint(monthly['plan_text']), type='discrete', archived=False)
        self.store.save_learning_items(monthly, [item])
        output = json.loads(generation_output())
        output['lessons'][1]['monthly_item_links'] = [dict(item_id='test-item', coverage='Opening paragraph')]
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps(output))
        app = self.new_app()
        app.date_input[0].set_value(date(2026, 9, 30)).run()
        self.button(app, "✨ Generate Today's Plan").click().run()
        self.button(app, 'Mark all completed').click().run()
        next(i for i in app.text_input if i.label == 'English — Narrative openings note (optional)').set_value('Whole opening paragraph finished')
        lesson = self.store.load_day('2026-09-30')['plan']['lessons'][1]
        item_schema = self.client.responses.create.call_args_list[0].kwargs['text']['format']['schema']['properties']['lessons']['items']['properties']['monthly_item_links']['items']['properties']['item_id']
        self.assertEqual(item_schema['enum'], ['test-item'])
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps({'updates':[dict(lesson_id=lesson['lesson_id'], item_id='test-item', status='Completed', remaining='', evidence='Whole opening paragraph finished')]}))
        self.button(app, 'Suggest item outcomes from notes').click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.list_learning_items()[0]['status'], 'Not started')
        self.assertEqual(self.store.load_progress_history(), [])
        next(i for i in app.checkbox if i.label == 'Whole item completed — explicitly confirm').check()
        self.button(app, "Save Today's Progress").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.list_learning_items()[0]['status'], 'Completed')

    def test_mixed_partial_note_requires_review_before_durable_save(self):
        import json
        from monthly_learning import fingerprint
        monthly = self.store.select_monthly_plan('2026-09-30')
        items = [dict(id=id, monthly_plan_id='9', subject='English', description=description, source='English narrative.', fingerprint=fingerprint(monthly['plan_text']), type='discrete', archived=False) for id, description in [('opening', 'Opening paragraph'), ('ending', 'Final activity')]]
        self.store.save_learning_items(monthly, items)
        output = json.loads(generation_output())
        output['lessons'][1]['monthly_item_links'] = [dict(item_id=i['id'], coverage=i['description']) for i in items]
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps(output))
        app = self.new_app()
        app.date_input[0].set_value(date(2026, 9, 30)).run()
        self.button(app, "✨ Generate Today's Plan").click().run()
        self.button(app, 'Mark all completed').click().run()
        next(i for i in app.radio if i.label == 'English — Narrative openings progress').set_value('Partially completed')
        next(i for i in app.text_input if i.label == 'English — Narrative openings note (optional)').set_value('Opening finished; final activity unfinished')
        lesson = self.store.load_day('2026-09-30')['plan']['lessons'][1]
        proposals = [dict(lesson_id=lesson['lesson_id'], item_id='opening', status='Completed', remaining='', evidence='Opening finished'), dict(lesson_id=lesson['lesson_id'], item_id='ending', status='In progress', remaining='final activity unfinished', evidence='final activity unfinished')]
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps({'updates': proposals}))
        self.button(app, "Save Today's Progress").click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(self.store.load_progress_history(), [])
        self.assertTrue(all(i['status'] == 'Not started' for i in self.store.list_learning_items()))
        next(i for i in app.checkbox if i.label == 'Whole item completed — explicitly confirm').check()
        self.button(app, "Save Today's Progress").click().run()
        self.assertEqual(len(app.exception), 0)
        current = {i['id']: i for i in self.store.list_learning_items()}
        self.assertEqual(current['opening']['status'], 'Completed')
        self.assertEqual(current['ending']['remaining'], 'final activity unfinished')

    def test_thursday_generation_cannot_overwrite_singing(self):
        import json
        self.store.save_document("teacher_profile", {"class_level": "5th Class", "thursday_singing": True})
        previous = sample_plan("2026-10-01")
        self.store.save_day_plan(previous)
        self.client.responses.create.return_value = SimpleNamespace(output_text=generation_output())
        app = self.new_app()
        app.date_input[0].set_value(date(2026, 10, 1)).run()
        self.button(app, "✨ Generate Today's Plan").click().run()
        self.assertEqual(len(app.error), 1)
        self.assertEqual(self.store.load_day("2026-10-01")["plan"], previous)
        self.assertIn("PROTECTED THURSDAY", self.client.responses.create.call_args_list[0].kwargs["input"])
        output = json.loads(generation_output())
        output["lessons"] = [l for l in output["lessons"] if l["time"] < "13:00"]
        output["overview"] = "09:30–10:00 Maths\n11:15–11:55 English\n13:50–14:00 Pack up / tidy up\n14:00–14:30 Singing — external teacher"
        self.client.responses.create.return_value = SimpleNamespace(output_text=json.dumps(output))
        self.button(app, "✨ Generate Today's Plan").click().run()
        self.assertEqual(len(app.error), 0)
        self.assertIn("Singing", self.store.load_day("2026-10-01")["plan"]["overview"])

    def test_linked_completion_and_manual_controls(self):
        import json
        october = self.store.select_monthly_plan("2026-10-01")
        with self.store._connection() as connection:
            connection.execute("DELETE FROM period_reviews")
        item = {"id": "carry", "period_id": october["id"], "subject": "English", "learning": "Finish final activity", "evidence": "September partial", "created_date": "2026-10-01", "state": "outstanding"}
        self.store.save_period_review(october, "2026-10-01", [item], True)
        output = json.loads(generation_output())
        output["lessons"][1]["carryover_ids"] = ["carry"]
        output["lessons"][1]["details"] += "\nCarryover: Finish final activity"
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
        self.assertEqual(self.client.responses.create.call_count, 2)

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

