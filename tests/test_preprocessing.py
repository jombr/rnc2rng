import unittest

import rnc2rng
from rnc2rng import parser
from rply.errors import LexingError


class PreprocessingTests(unittest.TestCase):
    def test_normalization_preserves_source_positions(self):
        source = parser._preprocess_source('\ufeffa\r\nb\rc\n')
        self.assertEqual(source.text, 'a\0b\0c\0')
        self.assertEqual([source.original[i] for i in source.offsets],
                         ['a', '\r', 'b', '\r', 'c', '\n'])
        pos = source.position(source.offsets[2])
        self.assertEqual((pos.lineno, pos.colno), (2, 1))

    def test_physical_line_endings_and_bom(self):
        expected = rnc2rng.dumps(rnc2rng.loads('start = element root { empty }'))
        for separator in ('\n', '\r', '\r\n'):
            src = '\ufeffstart = element root {' + separator + 'empty }'
            with self.subTest(separator=repr(separator)):
                self.assertEqual(rnc2rng.dumps(rnc2rng.loads(src)), expected)
        with self.assertRaisesRegex(parser.ParseError, 'Invalid XML character'):
            rnc2rng.loads('start = element root { "\0" }')
        with self.assertRaises(LexingError):
            rnc2rng.loads('start = element root { "x\ny" }')

    def test_original_location_after_crlf(self):
        src = 'start = element root {\r\n  @\r\n}'
        with self.assertRaises(LexingError) as error:
            rnc2rng.loads(src)
        self.assertEqual((error.exception.source_pos.idx, error.exception.source_pos.lineno,
                          error.exception.source_pos.colno), (src.index('@'), 2, 3))


if __name__ == '__main__':
    unittest.main()
