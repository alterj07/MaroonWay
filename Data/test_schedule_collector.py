import csv
import json
import tempfile
import unittest
from pathlib import Path
import collect_spring_schedule as c


class ScheduleTests(unittest.TestCase):
    def raw(self):
        return {c.PREFIX+k:v for k,v in {'TERM':'202711','CRN':'12345','SUBJECT':'CSCE','COURSE':'120','SECTION':'200',
            'SITE':'Galveston','TITLE':'TEST','INST_TYPE':'Traditional Face-to-Face (F2F)','ATTRIBUTES':'College Station| Honors',
            'INSTRCTR_JSON':json.dumps([{'NAME':'Martin Carlisle (P)'}]),
            'JSON_CLOB':json.dumps([{'SSRMEET_MON_DAY':'M','SSRMEET_BEGIN_TIME':'12:00 PM','SSRMEET_END_TIME':'01:00 PM',
                'SSRMEET_START_DATE':'01/19/2027','SSRMEET_END_DATE':'05/11/2027','SSRMEET_MTYP_CODE':'Lecture'},
                {'SSRMEET_WED_DAY':'W','SSRMEET_BEGIN_TIME':'09:10 AM','SSRMEET_END_TIME':'10:00 AM','SSRMEET_MTYP_CODE':'Laboratory'}])}.items()}

    def test_multiple_meetings_and_actual_site(self):
        s=c.normalize_section(self.raw(),'Spring 2027 - College Station','now')
        self.assertEqual(s['campus'],'Galveston')
        self.assertEqual(s['term_campus'],'College Station')
        self.assertTrue(s['is_honors'])
        m=json.loads(s['meetings_json'])
        self.assertEqual(len(m),2)
        self.assertEqual(m[0]['start_time'],'12:00')
        self.assertEqual(m[1]['type'],'Laboratory')

    def test_tba_is_not_asynchronous(self):
        r=self.raw();r[c.PREFIX+'JSON_CLOB']=None;r[c.PREFIX+'INST_TYPE']='Non-traditional';r[c.PREFIX+'SITE']=None
        s=c.normalize_section(r,'Spring 2027 - College Station','now')
        self.assertEqual(s['campus'],'Unknown')
        self.assertIsNone(s['is_online'])
        self.assertEqual(s['meeting_time_status'],'no_fixed_times')
        self.assertIsNone(c.clock_time('TBA'))
        with self.assertRaises(ValueError):c.clock_time('not a time')

    def test_office_hours_scope(self):
        s=c.normalize_section(self.raw(),'Spring 2027 - College Station','now')
        html='<div>Spring 2027 - College Station CSCE 120 12345</div><div class="component-wrapper"><h2>Instructor Details</h2><p>Martin Carlisle</p><p>Office Location: PETR 221</p><p>Office Hours</p><p>See Canvas</p></div>'
        r=c.extract_office_hours(html,s,'https://example.org')
        self.assertEqual(r['office_hours_status'],'login_required')
        self.assertEqual(r['office_location_text'],'PETR 221')
        self.assertEqual(r['office_hours_term_status'],'Spring 2027 confirmed')
        self.assertEqual(c.extract_office_hours(html.replace('2027','2026'),s,'url')['office_hours_status'],'source_mismatch_needs_review')

    def test_history_link_and_campus_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.csv'
            c.write_csv(p,[dict(campus='College Station',subject='CSCE',course_number='120',instructor_name='CARLISLE M',rmp_name='Martin Carlisle',level='Undergraduate',rmp_professor_id='1')])
            s=c.normalize_section(self.raw(),'Spring 2027 - College Station','now')
            c.link_history([s],p)
            self.assertEqual(s['grade_rmp_match_status'],'unmatched')
            s['campus']='College Station';c.link_history([s],p)
            self.assertEqual(s['grade_rmp_match_status'],'matched')
            self.assertEqual(json.loads(s['grade_rmp_links_json'])[0]['rmp_professor_id'],'1')

    def test_csv_json_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.csv';s=c.normalize_section(self.raw(),'Spring 2027 - College Station','now')
            s['office_hours_text']='Monday, 3 pm\n"Appointment"'
            c.write_csv(p,[s])
            with p.open(newline='') as f:r=next(csv.DictReader(f))
            self.assertEqual(r['office_hours_text'],s['office_hours_text'])
            self.assertEqual(json.loads(r['meetings_json']),json.loads(s['meetings_json']))


if __name__=='__main__': unittest.main()
