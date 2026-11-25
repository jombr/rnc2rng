import rnc2rng
import tempfile
import unittest
import xml.etree.ElementTree as ET
from rnc2rng.parser import ParseError
from urllib.parse import urlparse
from urllib.request import url2pathname
from pathlib import Path
import importlib.resources as resources
from . import golden


class TestSuite(unittest.TestCase):
    def test_from_string(self):
        with (
            resources.open_text(golden, "features.rnc") as src,
            resources.open_text(golden, "features.rng") as expect_src,
        ):
            expected = expect_src.read().rstrip()
            actual = rnc2rng.dumps(rnc2rng.loads(src.read())).strip()
            self.assertEqual(expected, actual)

    def _is_golden(self, fn):
        root = rnc2rng.load(fn)
        ref = fn.replace(".rnc", ".rng")
        if ref.startswith("file:"):
            parse_result = urlparse(ref)
            ref = url2pathname(parse_result.path)
        # Extract just the filename for resources.open_text
        ref = Path(ref).name
        with resources.open_text(golden, ref) as expect_src:
            expected = expect_src.read().rstrip()
            actual = rnc2rng.dumps(root).strip()
            self.assertEqual(expected, actual)

    def test_data_files_exist(self):
        self.assertNotEqual(list(resources.files(golden).iterdir()), [])

    def test_golden(self):
        for fn in filter(
            lambda f: f.suffix == ".rnc", resources.files(golden).iterdir()
        ):
            with self.subTest(fn=fn):
                self._is_golden(str(fn))

    def test_unknown_include_inherit_prefix(self):
        with self.assertRaisesRegex(ParseError, "Unknown namespace prefix"):
            rnc2rng.loads('include "child.rnc" inherit = missing\n')

    def test_unknown_external_inherit_prefix(self):
        with self.assertRaisesRegex(ParseError, "Unknown namespace prefix"):
            rnc2rng.loads('external "child.rnc" inherit = missing\n')

    def test_unknown_namespace_wildcard_prefix(self):
        for prefix in ("missing", "a"):
            for name_class in (f"{prefix}:*", f"({prefix}:* - {prefix}:name)"):
                with self.subTest(name_class=name_class):
                    source = f"start = element root {{ attribute {name_class} {{ text }}* }}"
                    with self.assertRaises(KeyError) as error:
                        rnc2rng.dumps(rnc2rng.loads(source))
                    self.assertEqual(error.exception.args, (prefix,))

    def test_empty_datatype_parameters(self):
        for datatype in ("string", "token", "xsd:string"):
            with self.subTest(datatype=datatype):
                plain = rnc2rng.dumps(rnc2rng.loads(f"element root {{ {datatype} }}"))
                empty = rnc2rng.dumps(rnc2rng.loads(f"element root {{ {datatype} {{}} }}"))
                self.assertEqual(plain, empty)

    def test_datatype_exception_requires_grouping(self):
        for pattern in ('xsd:token - "x" | "y"', 'xsd:token - "x"*'):
            with self.subTest(pattern=pattern), self.assertRaises(ParseError):
                rnc2rng.loads(f"element root {{ {pattern} }}")

    def test_nested_grammar_retains_wrapper(self):
        body = 'start = element root { empty }'
        nested = rnc2rng.dumps(rnc2rng.loads('start = grammar { ' + body + ' }'))
        root = ET.fromstring(nested)
        ns = '{http://relaxng.org/ns/structure/1.0}'
        self.assertIsNotNone(root.find(ns + 'start/' + ns + 'grammar/' + ns + 'start'))

    def test_included_top_level_grammar(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / 'child.rnc').write_text(
                'namespace a = "urn:child"\n'
                'grammar { a:note [ "child" ] start = element root { empty } }',
                encoding='utf-8',
            )
            (path / 'parent.rnc').write_text(
                'default namespace = "urn:parent"\n'
                'namespace a = "urn:outer"\n'
                'include "child.rnc"',
                encoding='utf-8',
            )
            root = ET.fromstring(rnc2rng.dumps(rnc2rng.load(str(path / 'parent.rnc'))))
        ns = '{http://relaxng.org/ns/structure/1.0}'
        self.assertEqual([child.tag for child in root],
                         ['{urn:child}note', ns + 'start'])
        self.assertEqual(root.find('{urn:child}note').text, 'child')
        name = root.find(ns + 'start/' + ns + 'element/' + ns + 'name')
        self.assertEqual((name.text, name.get('ns')), ('root', 'urn:parent'))

    # synthesize a test that reads its input from a URL
    def test_urlinput(self):
        with resources.path(golden, "include.rnc") as path:
            self._is_golden(path.absolute().as_uri())


if __name__ == "__main__":
    unittest.main()
