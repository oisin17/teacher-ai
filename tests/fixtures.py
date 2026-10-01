import copy
import json
from lesson_progress import parse_generated_plan


def generation_output():
    output = {
        "overview": "09:30–10:00 Maths\n11:15–11:55 English\n13:20–13:50 Gaeilge",
        "lessons": [
            {"time": "09:30–10:00", "subject": "Maths", "topic": "Rounding to 1000",
             "learning_intention": "Round five-digit numbers to the nearest 1000.",
             "details": "Resources: mini-whiteboards. Model 5 min; practise 20 min; assess 5 min."},
            {"time": "11:15–11:55", "subject": "English", "topic": "Narrative openings",
             "learning_intention": "Use a hook and sensory description in an opening paragraph.",
             "details": "Model a hook, draft an opening, then improve the final sensory detail."},
            {"time": "13:20–13:50", "subject": "Gaeilge", "topic": "Mé Féin conversation",
             "learning_intention": "Ask and answer three questions about yourself.",
             "details": "Model three questions and practise in pairs."},
        ],
    }
    for l in output['lessons']:
        from timetable_constraints import interval
        start,end = interval(l['time'])
        l['phases'] = [dict(minutes=5, activity='Model the task'),dict(minutes=end-start-10,activity='Practise the learning'),dict(minutes=5,activity='Check understanding and tidy up')]
    return json.dumps(output)


def sample_plan(day="2026-09-30"):
    return parse_generated_plan(generation_output(), day)


def outcomes(plan):
    lessons = copy.deepcopy(plan["lessons"])
    for item, status, note in zip(lessons,
        ["Completed", "Partially completed", "Not taught"],
        ["", "didn't finish final activity", "not taught because of assembly"]):
        item.update(status=status, note=note)
    return lessons
