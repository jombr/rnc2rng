import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import rnc2rng
from rnc2rng import parser, rnctree
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

    def test_original_location_after_comment_lines(self):
        src = '# ignored\r\n' * 4 + 'start = element root {\r\n  @\r\n}'
        with self.assertRaises(LexingError) as error:
            rnc2rng.loads(src)
        self.assertEqual((error.exception.source_pos.idx, error.exception.source_pos.lineno,
                          error.exception.source_pos.colno), (src.index('@'), 6, 3))

        src = '# ignored\r\n' * 4 + 'start = element root {\r\n  | empty\r\n}'
        with self.assertRaises(parser.ParseError) as error:
            rnc2rng.loads(src)
        self.assertEqual(error.exception.location, (None, 5, 2))
        self.assertEqual(error.exception.line, '  | empty')

    def test_escape_replacement_and_nonrecursive_scanning(self):
        source = parser._preprocess_source(
            r'\x{61} \xxx{6F} \x{1F600} \x{5C}x{61} \\x{61} \xhello \X{61}'
        )
        self.assertEqual(source.text, 'a o \U0001f600 \\x{61} \\a \\xhello \\X{61}')
        self.assertEqual(parser._preprocess_source(r'\x{A}\x{D}').text, '\n\r')

    def test_malformed_and_invalid_escapes(self):
        for escape in (r'\x{}', r'\x{G}', r'\x{61', r'\x{0}',
                       r'\x{D800}', r'\x{FFFE}', r'\x{110000}'):
            with self.subTest(escape=escape):
                source = '# comment ' + escape + '\nstart = element root { empty }'
                with self.assertRaises(parser.ParseError) as error:
                    rnc2rng.loads(source)
                self.assertEqual(error.exception.location[1], 0)
                self.assertIn('escape', str(error.exception).lower())
                self.assertEqual(error.exception.line, source.splitlines()[0])

    def test_malformed_escape_location_after_earlier_escape(self):
        source = 'start = element root { "' + r'\x{61}\x{}' + '" }'
        with self.assertRaises(parser.ParseError) as error:
            rnc2rng.loads(source)
        self.assertEqual(error.exception.location, (None, 0, source.index(r'\x{}') + 3))

    def test_original_locations_after_escapes(self):
        src = r'start = element \x{72}oot { | }'
        with self.assertRaises(parser.ParseError) as error:
            rnc2rng.loads(src)
        self.assertEqual(error.exception.location, (None, 0, src.index('|')))
        src = r'start = element \x{72}oot { @ }'
        with self.assertRaises(LexingError) as error:
            rnc2rng.loads(src)
        self.assertEqual(error.exception.source_pos.idx, src.index('@'))
        self.assertEqual(error.exception.source_pos.colno, src.index('@') + 1)
        src = '\ufeffstart = element root { ' + r'\x{A}' + ' | }'
        with self.assertRaises(parser.ParseError) as error:
            rnc2rng.loads(src)
        self.assertEqual(error.exception.location, (None, 0, src.index('|') - 1))
        self.assertEqual(error.exception.line, src[1:])
        src = 'start = element root {\r\n' + r'\x{61} @' + '\r\n}'
        with self.assertRaises(LexingError) as error:
            rnc2rng.loads(src)
        self.assertEqual((error.exception.source_pos.lineno, error.exception.source_pos.colno),
                         (2, 8))

    def test_error_location_for_literal_beginning_with_escaped_lf(self):
        src = 'start = element root {\n  empty "' + r'\x{A}bad' + '"\n}'
        with self.assertRaises(parser.ParseError) as error:
            rnc2rng.loads(src)
        self.assertEqual(error.exception.token.value, '\nbad')
        self.assertEqual(error.exception.location, (None, 1, 8))
        self.assertEqual(error.exception.line, '  empty "' + r'\x{A}bad' + '"')

    def test_escaped_newlines_in_literals_and_comments(self):
        src = r'start = element root { xsd:string "x\x{A}y\x{D}z" }'
        xml = rnc2rng.dumps(rnc2rng.loads(src))
        value = next(ET.fromstring(xml).iter('{http://relaxng.org/ns/structure/1.0}value'))
        self.assertEqual(value.text, 'x\ny\rz')
        with self.assertRaises(LexingError):
            rnc2rng.loads(r'start\x{D}= element root { empty }')
        src = r'# ignored \x{A} start = element root { empty }'
        self.assertIn('<name ns="">root</name>', rnc2rng.dumps(rnc2rng.loads(src)))
        src = r'\x{23} ignored' + '\nstart = element root { empty }'
        self.assertIn('<name ns="">root</name>', rnc2rng.dumps(rnc2rng.loads(src)))
        with self.assertRaises(parser.ParseError):
            rnc2rng.loads(r'start = element root { "x\x{22}y" }')

    def test_escapes_in_include_and_compatibility_token_path(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            child = path / 'child.rnc'
            child.write_text(r'start = element \x{72}oot { "\x{61}" }', encoding='utf-8')
            parent = path / 'parent.rnc'
            parent.write_text('include "child.rnc"', encoding='utf-8')
            self.assertIn('<value>a</value>', rnc2rng.dumps(rnc2rng.load(str(parent))))
            child.write_text(r'start = element root { "\x{}" }', encoding='utf-8')
            with self.assertRaises(parser.ParseError) as error:
                rnc2rng.load(str(parent))
            self.assertEqual(error.exception.location[0], str(child))
        tokens = list(rnctree.token_list(r'element \x{72}oot { empty }'))
        self.assertEqual([t.name for t in tokens], ['ELEMENT', 'ID', 'LBRACE', 'EMPTY', 'RBRACE'])
        self.assertEqual(tokens[1].value, 'root')


if __name__ == '__main__':
    unittest.main()
