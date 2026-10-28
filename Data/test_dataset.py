import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
import build_dataset as b


class DatasetTests(unittest.TestCase):
    def row(self, **kw):
        r = dict(file='2026SPRING_EN.pdf', level='Undergraduate', term='SPRING 2026',
                 subject='CSCE', number='120', section='500', instructor='LEYK Z',
                 department='COMPUTER SCIENCE & ENGINEERING', A='2', B='1', C='0', D='0', F='1', AF='4', TOTAL='4')
        r.update(kw)
        return r

    def prof(self, **kw):
        p = dict(campus='College Station', firstName='Zbigniew', lastName='Leyk',
                 department='Computer Science', legacyId=1, avgRating=4.0,
                 avgDifficulty=2.5, numRatings=25, wouldTakeAgainPercent=-1)
        p.update(kw)
        return p

    def test_campus_dedup_and_weighted_grades(self):
        rows = b.aggregate_sections([self.row(), self.row(), self.row(file='2026SPRING_QT.pdf'),
                                     self.row(section='501', A='0', B='0', F='1', AF='1', TOTAL='1')])
        self.assertEqual(len(rows), 2)
        cs = next(r for r in rows if r['campus'] == 'College Station')
        self.assertEqual(cs['graded_students'], 5)
        self.assertEqual(cs['avg_gpa'], 2.2)
        self.assertEqual(cs['section_count'], 2)

    def test_zero_students(self):
        r = b.aggregate_sections([self.row(A='0', B='0', F='0', AF='0')])[0]
        self.assertIsNone(r['avg_gpa'])

    def test_matching_campus_and_ambiguity(self):
        g = b.aggregate_sections([self.row()])[0]
        self.assertIsNotNone(b.match(g, [self.prof()])[0])
        self.assertIsNone(b.match(g, [self.prof(campus='Galveston')])[0])
        self.assertIsNone(b.match(g, [self.prof(), self.prof(legacyId=2)])[0])
        # This line used to assert the opposite. A department that disagrees no
        # longer vetoes a professor who is the only candidate by name: that
        # rule discarded 5,485 rows whose one candidate was the right one, and
        # is why most instructors carried no rating. See match()'s docstring.
        self.assertIsNotNone(b.match(g, [self.prof(department='English')])[0])

    def test_review_dates_course_labels_and_missing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reviews = [dict(id=str(i), date=d, **{'class': c}, comment='comma, quote " and\nnewline')
                       for i, (d, c) in enumerate([('2025-10-24', 'CSCE120'), ('2026-10-24', '120'),
                                                   ('2025-10-23', 'CSCE120'), ('2026-10-25', 'CSCE120'), ('bad', '120')])]
            b.save_json(root / 'reviews_1.json', dict(complete=True, reviews=reviews))
            with patch.object(b, 'OUT', root), patch.object(b, 'CACHE', root):
                rows = b.attach_rmp(b.aggregate_sections([self.row()]), [self.prof()], date(2026, 10, 24))
                self.assertEqual(rows[0]['reviews_past_year_count'], 2)
                self.assertEqual(rows[0]['reviews_invalid_date_count'], 1)
                self.assertEqual(len(json.loads(rows[0]['rmp_course_reviews_past_year_json'])), 1)
                self.assertIsNone(rows[0]['rmp_would_take_again_pct'])
                b.write_csv(root / 'test.csv', rows)
                self.assertEqual(json.loads(b.read_csv(root / 'test.csv')[0]['rmp_reviews_past_year_json']), json.loads(rows[0]['rmp_reviews_past_year_json']))

    def test_leap_year(self):
        self.assertEqual(b.year_before(date(2024, 2, 29)), date(2023, 2, 28))


if __name__ == '__main__':
    unittest.main()


class NameKeyTests(unittest.TestCase):
    """The three name forms we actually receive.

    Only the grade reports' "CANTU J" existed when name_key was written, so
    everything else returned None and never reached the matcher at all.
    """

    def test_grade_report_surname_then_initial(self):
        self.assertEqual(b.name_key('CANTU J'), ('CANTU', 'J'))

    def test_schedule_builder_surname_comma_given(self):
        self.assertEqual(b.name_key('Cantu, Justin Colt'), ('CANTU', 'JUSTIN'))

    def test_given_name_first(self):
        self.assertEqual(b.name_key('Justin Colt Cantu'), ('CANTU', 'JUSTIN'))

    def test_multi_word_surname_keeps_its_parts(self):
        self.assertEqual(b.name_key('VAN DER BERG J'), ('VAN DER BERG', 'J'))

    def test_suffixes_are_not_names(self):
        self.assertEqual(b.name_key('Chupp, Jesse A Jr'), ('CHUPP', 'JESSE'))

    def test_a_lone_word_is_unreadable(self):
        self.assertIsNone(b.name_key('STAFF'))


class NamesAgreeTests(unittest.TestCase):
    def test_an_initial_agrees_with_the_name_it_abbreviates(self):
        self.assertTrue(b.names_agree('J', 'JUSTIN'))
        self.assertTrue(b.names_agree('JUSTIN', 'J'))

    def test_the_same_name_agrees_with_itself(self):
        self.assertTrue(b.names_agree('JUSTIN', 'JUSTIN'))

    def test_different_names_do_not_agree(self):
        self.assertFalse(b.names_agree('JUSTIN', 'MICHAEL'))

    def test_a_longer_name_is_not_a_different_one(self):
        """JUSTIN and JUSTINE are two people, and a fuzzy rule would merge them."""
        self.assertTrue(b.names_agree('JUSTIN', 'JUSTINE'))
        self.assertFalse(b.names_agree('JUSTINE', 'JUSTIN0'))

    def test_a_missing_name_agrees_with_nothing(self):
        self.assertFalse(b.names_agree('', 'JUSTIN'))
        self.assertFalse(b.names_agree('J', ''))


class MatcherTests(unittest.TestCase):
    """Department is a tiebreak now, not a precondition.

    The old rule discarded a uniquely-matched professor unless RMP's
    department string overlapped the grade report's by half its tokens. That
    is the single biggest reason instructors carry no rating.
    """

    def row(self, **kw):
        r = dict(file='2026SPRING_EN.pdf', level='Undergraduate', term='SPRING 2026',
                 subject='AERO', number='201', section='500', instructor='DEMARS K',
                 department='AEROSPACE ENGINEERING', A='2', B='1', C='0', D='0', F='1',
                 AF='4', TOTAL='4')
        r.update(kw)
        return r

    def prof(self, **kw):
        p = dict(campus='College Station', firstName='Kyle', lastName='Demars',
                 department='Mechanical Engineering', legacyId=7, avgRating=4.0,
                 avgDifficulty=2.5, numRatings=25, wouldTakeAgainPercent=-1)
        p.update(kw)
        return p

    def group(self, **kw):
        return b.aggregate_sections([self.row(**kw)])[0]

    def test_a_unique_name_match_no_longer_needs_the_department_to_agree(self):
        found, status, _ = b.match(self.group(), [self.prof()])

        self.assertIsNotNone(found, "the only candidate was the right one")
        self.assertEqual(status, 'matched_name_unique')

    def test_a_full_first_name_matches_an_initial_in_the_grade_report(self):
        found, status, _ = b.match(self.group(), [self.prof(firstName='Kyle James')])

        self.assertIsNotNone(found)
        self.assertEqual(status, 'matched_name_unique')

    def test_the_department_still_decides_between_namesakes(self):
        aero = self.prof(firstName='Kyle', department='Aerospace Engineering', legacyId=1)
        other = self.prof(firstName='Kyle', department='History', legacyId=2)

        found, status, candidates = b.match(self.group(), [aero, other])

        self.assertEqual(status, 'matched_name_department')
        self.assertEqual(found['legacyId'], 1)
        self.assertEqual(len(candidates), 2)

    def test_namesakes_the_department_cannot_separate_go_to_review(self):
        one = self.prof(firstName='Kyle', department='History', legacyId=1)
        two = self.prof(firstName='Kyle', department='History', legacyId=2)

        found, status, candidates = b.match(self.group(), [one, two])

        self.assertIsNone(found, "guessing between two people is worse than asking")
        self.assertEqual(status, 'needs_review')
        self.assertEqual(len(candidates), 2)

    def test_a_different_campus_is_a_different_person(self):
        found, status, _ = b.match(self.group(), [self.prof(campus='Galveston')])

        self.assertIsNone(found)
        self.assertEqual(status, 'no_match')

    def test_a_different_surname_does_not_match(self):
        found, status, _ = b.match(self.group(), [self.prof(lastName='Demarco')])

        self.assertIsNone(found)
        self.assertEqual(status, 'no_match')

    def test_a_wrong_first_initial_does_not_match(self):
        found, status, _ = b.match(self.group(), [self.prof(firstName='Robert')])

        self.assertIsNone(found)
        self.assertEqual(status, 'no_match')

    def test_an_unreadable_name_is_reported_as_such(self):
        found, status, candidates = b.match(self.group(instructor='STAFF'), [self.prof()])

        self.assertIsNone(found)
        self.assertEqual(status, 'unmatched_name_format')
        self.assertEqual(candidates, [])
