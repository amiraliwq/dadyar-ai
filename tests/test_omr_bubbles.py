import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "omr-service"))
from main import bubble_score, classify_bubble_scores


class BubbleScoringTests(unittest.TestCase):
    def make_bubble(self, fill=None, background=245):
        image = np.full((120, 120), background, dtype=np.uint8)
        cv2.circle(image, (60, 60), 16, 25, 2, lineType=cv2.LINE_AA)
        if fill is not None:
            cv2.circle(image, (60, 60), 9, fill, -1, lineType=cv2.LINE_AA)
        return image

    def score(self, image):
        return bubble_score(image, 60, 60, 16, 16)

    def test_empty_bubble_is_low_score(self):
        self.assertLess(self.score(self.make_bubble()), 0.16)

    def test_dark_fill_is_high_score(self):
        self.assertGreater(self.score(self.make_bubble(fill=20)), 0.65)

    def test_light_pencil_fill_is_detected(self):
        self.assertGreater(self.score(self.make_bubble(fill=130)), 0.35)

    def test_single_clear_answer(self):
        answer, review = classify_bubble_scores([0.72, 0.08, 0.06, 0.05], 1)
        self.assertEqual(answer, 1)
        self.assertIsNone(review)

    def test_multiple_marks_require_review(self):
        answer, review = classify_bubble_scores([0.75, 0.66, 0.06, 0.04], 2)
        self.assertIsNone(answer)
        self.assertIn("بیش از یک", review["reason"])

    def test_faint_or_close_marks_require_review(self):
        answer, review = classify_bubble_scores([0.31, 0.27, 0.12, 0.10], 3)
        self.assertIsNone(answer)
        self.assertIsNotNone(review)

    def test_blank_remains_blank(self):
        answer, review = classify_bubble_scores([0.08, 0.07, 0.06, 0.05], 4)
        self.assertIsNone(answer)
        self.assertIsNone(review)


if __name__ == "__main__":
    unittest.main()
