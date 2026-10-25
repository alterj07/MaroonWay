import json
import tempfile
import unittest
from pathlib import Path
from prerequisites import extract_requirements, attach_prerequisites, fill_missing_prerequisites


class PrerequisiteTests(unittest.TestCase):
    def test_prerequisite_word_in_prose(self):
        r=extract_requirements('This course is a prerequisite for later courses. Prerequisite: Approval of instructor; programs may have additional prerequisites.')
        self.assertEqual(r['prerequisite_text'],'Approval of instructor; programs may have additional prerequisites.')

    def test_conditions_and_crosslist(self):
        r = extract_requirements('A class. Prerequisites: Grade C or better in CSCE 120 or CSCE 121; grade of C or better in CSCE 222 or ECEN 222, or concurrent enrollment. Cross Listing: ECEN 221.')
        self.assertEqual(r['prerequisite_text'], 'Grade C or better in CSCE 120 or CSCE 121; grade of C or better in CSCE 222 or ECEN 222, or concurrent enrollment.')
        self.assertNotIn('Cross Listing', r['prerequisite_text'])

    def test_nonstandard_headings(self):
        for text in ['Prerequisite(s): Graduate classification.', 'Prerequisites Graduate classification.']:
            self.assertEqual(extract_requirements(text)['prerequisite_text'], 'Graduate classification.')

    def test_corequisite_and_none(self):
        r = extract_requirements('Prerequisite: MATH 151. Corequisite: PHYS 206.')
        self.assertEqual(r['corequisite_text'], 'PHYS 206.')
        self.assertEqual(r['prerequisite_text'], 'MATH 151.')
        self.assertEqual(extract_requirements('Description only.')['prerequisite_status'], 'not_listed_in_catalog')
        self.assertEqual(extract_requirements(None)['prerequisite_status'], 'catalog_description_missing')
        self.assertEqual(extract_requirements('Prerequisites: None.')['prerequisite_status'], 'explicitly_none')

    def test_term_specific_matching(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            for term, pre in [('202711','MATH 151'),('202712','MATH 150')]:
                (p/f'catalog_{term}.json').write_text(json.dumps([{'SCBCRKY_SUBJ_CODE':'TEST','SCBCRKY_CRSE_NUMB':'101','COURSE_NARRATIVE':f'Prerequisite: {pre}.'}]))
            sections = [{'term_code':t,'subject':'TEST','course_number':'101'} for t in ['202711','202712']]
            sections.append({'term_code':'202711','subject':'NONE','course_number':'100'})
            attach_prerequisites(sections,p)
            self.assertEqual(sections[0]['prerequisite_text'],'MATH 151.')
            self.assertEqual(sections[1]['prerequisite_text'],'MATH 150.')
            self.assertEqual(sections[2]['prerequisite_status'],'course_not_in_catalog')

    def test_cached_empty_section_response(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'section_prerequisites').mkdir()
            (p/'section_prerequisites/202711_123.json').write_text('{"P_PRE_REQS_OUT":null}')
            s={'term_code':'202711','crn':'123','prerequisite_status':'catalog_description_missing'}
            fill_missing_prerequisites(None,[s],p,offline=True)
            self.assertEqual(s['prerequisite_status'],'none_reported_by_section_search')
            self.assertTrue(s['prerequisite_section_verified'])


if __name__ == '__main__': unittest.main()
