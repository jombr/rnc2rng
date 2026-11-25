# Convert an RELAX NG compact syntax schema to a Node tree
# This file released to the Public Domain by David Mertz
from . import parser
from rnc2rng.parser import (
    ANNO_ATTR, ANNOTATION, ANY, ASSIGN, ATTR, CHOICE, DATATAG, DATATYPES,
    DEFAULT_NS, DEFINE, DIV, DOCUMENTATION, ELEM, EMPTY, EXCEPT, EXTERNAL,
    GRAMMAR,
    GROUP, INTERLEAVE, LIST, LITERAL, MAYBE, MIXED, NAME, NOT_ALLOWED, NS,
    PARAM, PARENT, REF, ROOT, SEQ, SOME, TEXT, LITERAL_TYPE
)

import html
from urllib.parse import urlsplit, urlunsplit

QUANTS = {SOME: 'oneOrMore', MAYBE: 'optional', ANY: 'zeroOrMore'}
TYPELIBS = {
    'xsd': 'http://www.w3.org/2001/XMLSchema-datatypes'
}
NAMESPACES = {
    'a': 'http://relaxng.org/ns/compatibility/annotations/1.0',
    'xml': 'http://www.w3.org/XML/1998/namespace',
}


# XML 1.0 section 2.11 normalizes literal CR to LF; use a character
# reference to preserve CR produced by Compact Syntax Appendix A.2.4.
def _escape_text(value):
    return html.escape(value).replace('\r', '&#xD;')


# XML 1.0 section 3.3.3 normalizes literal whitespace in attributes.
# Character references preserve the values used by Appendix A.1.
def _escape_attr(value):
    return _escape_text(value).replace('\n', '&#xA;').replace('\t', '&#x9;')


class XMLSerializer(object):

    def __init__(self, indent=None):
        self.indent = indent or '  '
        self.reset()

    def reset(self):
        self.buf = []
        self.ns = {}
        self.global_ns = {}
        self.typelibs = {}
        self.default = ''
        self.level = 0
        self.root_depth = 0

    def write(self, s):
        self.buf.append(self.indent * self.level + s)

    def datatype_library(self, prefix):
        assert prefix in self.typelibs or prefix in TYPELIBS, prefix
        if prefix not in self.typelibs:
            self.typelibs[prefix] = TYPELIBS[prefix]
        return self.typelibs[prefix]

    def namespace(self, ns):
        assert ns in self.ns or ns in NAMESPACES, ns
        if ns not in self.ns:
            self.ns[ns] = NAMESPACES[ns]
        return self.ns[ns]

    def wildcard_namespace(self, prefix):
        if prefix == 'xml' and prefix not in self.ns:
            return NAMESPACES['xml']
        return self.ns[prefix]

    def namespace_declaration(self, prefix, uri):
        if prefix == 'xml' or self.global_ns.get(prefix) == uri:
            return ''
        if self.root_depth:
            return ' xmlns:%s="%s"' % (prefix, _escape_attr(uri))
        self.ns[prefix] = uri
        return ''

    def documentation_namespace_declaration(self):
        # Compact Syntax section 5.2 fixes documentation shorthand's namespace.
        documentation_ns = NAMESPACES['a']
        self.namespace('a')
        if self.root_depth:
            global_binding_differs = self.global_ns.get('a') != documentation_ns
            local_binding_differs = self.ns.get('a') != documentation_ns
            needs_declaration = global_binding_differs or local_binding_differs
            if needs_declaration:
                return ' xmlns:a="%s"' % html.escape(documentation_ns)
            return ''
        if self.global_ns.get('a') not in (None, documentation_ns):
            return ' xmlns:a="%s"' % html.escape(documentation_ns)
        self.ns['a'] = documentation_ns
        return ''

    def toxml(self, node):

        self.reset()
        for n in node.value:
            if n.type == DATATYPES:
                self.typelibs[n.name] = n.value[0]
            elif n.type == DEFAULT_NS:
                self.default = n.value[0]
                if n.name is not None:
                    self.ns[n.name] = n.value[0]
            elif n.type == NS:
                self.ns[n.name] = n.value[0]

        self.global_ns = self.ns.copy()
        prelude = ['<?xml version="1.0" encoding="UTF-8"?>']
        prelude.append('<grammar xmlns="http://relaxng.org/ns/structure/1.0"')
        if self.default and self.default != 'inherit':
            prelude.append('         ns="%s"' % _escape_attr(self.default))

        self.visit_schema_contents(node.value)
        for ns, url in sorted(self.ns.items()):
            if url and url != 'inherit':
                prelude.append('         xmlns:%s="%s"' % (ns, _escape_attr(url)))

        # if xsd:* ever referenced, print it at the grammar level
        if 'xsd' in self.typelibs:
            prelude.append('         datatypeLibrary="%s"' % _escape_attr(self.typelibs['xsd']))

        prelude[-1] = prelude[-1] + '>'
        self.write('</grammar>')
        return '\n'.join(prelude + self.buf)

    def anno_attrs(self, nodes, extra_prefixes=()):
        select = lambda n: isinstance(n, parser.Node) and n.type == ANNO_ATTR
        pairs = []
        prefixes = set(extra_prefixes)
        for n in nodes:
            if not select(n):
                continue
            pairs.append((n.name, _escape_attr(n.value[0])))
            if n.name is not None and ':' in n.name:
                prefixes.add(n.name.split(':', 1)[0])

        declarations = []
        for prefix in sorted(prefixes):
            uri = self.namespace(prefix)
            declaration = self.namespace_declaration(prefix, uri)
            if declaration:
                declarations.append(declaration)

        attrs = ' ' + ' '.join('%s="%s"' % attr for attr in pairs) if pairs else ''
        return attrs + ''.join(declarations)

    def type_attrs(self, name):
        if ':' in name:
            prefix, name = name.split(':', 1)
            ns = self.datatype_library(prefix)
        else:
            assert name in ('string', 'token') # these are the only "built-in" datatypes
            ns = ""

        attrs = ' type="%s"' % name
        if ns != TYPELIBS['xsd']:
            attrs += ' datatypeLibrary="%s"' % _escape_attr(ns) # write all exceptions explicitly
        return attrs

    def map_schema_ref(self, uri):
        parts = urlsplit(uri)
        path = parts.path
        if path.endswith('.rnc'):
            path = path[:-4] + '.rng'
        else:
            path += '.rng'
        return urlunsplit((
            parts.scheme, parts.netloc, path, parts.query, parts.fragment
        ))

    def visit_root(self, root):
        outer_ns = self.ns
        outer_default = self.default
        self.ns = outer_ns.copy()
        self.root_depth += 1
        try:
            for n in root.value:
                if n.type == DATATYPES:
                    self.typelibs[n.name] = n.value[0]
                elif n.type == DEFAULT_NS:
                    self.default = n.value[0]
                    if n.name is not None:
                        self.ns[n.name] = n.value[0]
                elif n.type == NS:
                    self.ns[n.name] = n.value[0]
            self.visit_schema_contents(root.value, indent=False)
        finally:
            self.root_depth -= 1
            self.ns = outer_ns
            self.default = outer_default

    def visit_schema_contents(self, nodes, indent=True):
        # A schema-root grammar supplies members to the enclosing grammar.
        contents = []
        for node in nodes:
            if isinstance(node, parser.Node) and node.type == GRAMMAR:
                contents.extend(node.value)
            else:
                contents.append(node)
        self.visit(contents, indent=indent)

    def visit(self, nodes, ctx=None, indent=True):
        '''Visiting a list of nodes, writes out the XML content to the internal
        line-based buffer. By default, adds one level of indentation to the
        output compared to the caller's level; passing False as the second
        argument will prevent this from happening.'''
        if indent:
            self.level += 1
        for x in nodes:

            if not isinstance(x, parser.Node):
                raise TypeError("Not a Node: " + repr(x))
            elif x.type in set([ANNO_ATTR, LITERAL_TYPE, DATATYPES, DEFAULT_NS, NS]):
                continue

            annotation_prefixes = (
                [x.name.split(':', 1)[0]]
                if x.type == ANNOTATION and ':' in x.name else []
            )
            attribs = self.anno_attrs(x.value, annotation_prefixes)
            if x.type == DEFINE:
                for op in (x.name for x in x.value if x.type == 'ASSIGN'):
                    modes = {'|=': 'choice', '&=': 'interleave'}
                    if op in modes:
                        attribs = (' combine="%s"' % modes[op]) + attribs
                    break;

                if x.name == 'start':
                    self.write('<start%s>' % attribs)
                else:
                    bits = x.name, attribs
                    self.write('<define name="%s"%s>' % bits)

                self.visit(x.value)
                if x.name == 'start':
                    self.write('</start>')
                else:
                    self.write('</define>')

            elif x.type == ASSIGN:
                self.visit(x.value, indent=False)
            elif x.type == GRAMMAR:
                self.write('<grammar>')
                self.visit(x.value)
                self.write('</grammar>')
            elif x.type in set([MAYBE, SOME, ANY]):
                self.write('<%s%s>' % (QUANTS[x.type], attribs))
                self.visit(x.value)
                self.write('</%s>' % QUANTS[x.type])
            elif x.type in set([INTERLEAVE, CHOICE, MIXED, LIST, DIV]):
                self.write('<%s%s>' % (x.type.lower(), attribs))
                self.visit(x.value)
                self.write('</%s>' % x.type.lower())
            elif x.type == EXCEPT:
                self.write('<except>')
                self.visit(x.value, ctx=ctx)
                self.write('</except>')
            elif x.type == NAME:
                if not x.value and '*' in x.name:
                    if x.name == '*':
                        self.write('<anyName/>')
                    else:
                        uri = self.wildcard_namespace(x.name.split(':', 1)[0])
                        self.write('<nsName ns="%s"/>' % _escape_attr(uri))
                elif x.value:
                    if x.name == '*':
                        self.write('<anyName>')
                    else:
                        uri = self.wildcard_namespace(x.name.split(':', 1)[0])
                        self.write('<nsName ns="%s">' % _escape_attr(uri))
                    self.visit(x.value, ctx=ctx)
                    if x.name == '*':
                        self.write('</anyName>')
                    else:
                        self.write('</nsName>')
                else:
                    ns = '' if ctx == 'ATTR' else self.default
                    name = x.name
                    if ':' in name:
                        parts = x.name.split(':', 1)
                        ns = self.namespace(parts[0])
                        name = parts[1]
                    if ns == 'inherit':
                        self.write('<name>%s</name>' % name)
                    else:
                        self.write('<name ns="%s">%s</name>' % (_escape_attr(ns), name))
            elif x.type in set([REF, PARENT]):
                bits = x.type.lower(), x.name, attribs
                if not x.value: # no parameters
                    self.write('<%s name="%s"%s/>' % bits)
                else:
                    self.write('<%s name="%s"%s>' % bits)
                    self.visit(x.value)
                    self.write('</%s>' % x.type.lower())
            elif x.type == EXTERNAL:
                href = _escape_attr(self.map_schema_ref(x.name))
                inherited_namespace = x.value[0]
                ns_attr = ''
                if inherited_namespace != 'inherit':
                    ns_attr = ' ns="%s"' % _escape_attr(inherited_namespace)
                self.write('<externalRef href="%s"%s/>' % (href, ns_attr))
            elif x.type == LITERAL:
                types = [n.name for n in x.value if isinstance(n, parser.Node) and n.type == LITERAL_TYPE]
                if types:
                    assert len(types) == 1
                    attribs += self.type_attrs(types[0])

                bits = attribs, _escape_text(x.name)

                self.write('<value%s>%s</value>' % bits)
                self.visit(x.value, indent=False)
            elif x.type == ANNOTATION:
                literals, rest = [], []
                for n in x.value:
                    if n.type == LITERAL:
                        literals.append(n.name)
                    elif n.type != ANNO_ATTR:
                        rest.append(n)

                end = '/' if not (literals or rest) else ''
                tail = ''
                if literals and not rest:
                    tail = _escape_text(''.join(literals)) + '</%s>' % x.name

                bits = x.name, attribs, end, tail

                self.write('<%s%s%s>%s' % bits)
                if not rest:
                    continue

                for n in x.value:
                    if n.type == ANNO_ATTR:
                        continue
                    elif n.type == LITERAL:
                        self.level += 1
                        self.write(_escape_text(n.name))
                        self.level -= 1
                    else:
                        self.visit([n])

                self.write('</%s>' % x.name)

            elif x.type == DOCUMENTATION:
                xmlns_attr = self.documentation_namespace_declaration()

                fmt = '<a:documentation%s>%s</a:documentation>'
                self.write(fmt % (xmlns_attr, _escape_text('\n'.join(x.value))))
            elif x.type == GROUP:
                if len(x.value) == 1 and x.value[0].type != SEQ:
                    self.visit(x.value, indent=False)
                else:
                    self.write('<%s%s>' % (x.type.lower(), attribs))
                    self.visit(x.value)
                    self.write('</%s>' % x.type.lower())
            elif x.type == NOT_ALLOWED:
                self.write('<notAllowed%s/>' % attribs)
                self.visit(x.value, indent=False)
            elif x.type in set([TEXT, EMPTY]):
                self.write('<%s%s/>' % (x.type.lower(), attribs))
                self.visit(x.value, indent=False)
            elif x.type == SEQ:
                self.visit(x.value, indent=False)
            elif x.type == DATATAG:
                if not x.value:
                    self.write('<data%s%s/>' % (self.type_attrs(x.name), attribs))
                else:
                    self.write('<data%s%s>' % (self.type_attrs(x.name), attribs))
                    self.visit(x.value)
                    self.write('</data>')
            elif x.type == PARAM:
                bits = x.name, _escape_text(x.value[0])
                self.write('<param name="%s">%s</param>' % bits)
            elif x.type == ELEM:
                self.write('<element%s>' % attribs)
                self.visit(x.value)
                self.write('</element>')
            elif x.type == ATTR:
                self.write('<attribute%s>' % attribs)
                self.visit(x.value, ctx=x.type)
                self.write('</attribute>')
            elif x.type == ROOT:
                self.visit_root(x)
            else:
                assert False, x
        if indent:
            self.level -= 1
