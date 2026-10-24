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
        self.assertIsNone(b.match(g, [self.prof(department='English')])[0])

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
