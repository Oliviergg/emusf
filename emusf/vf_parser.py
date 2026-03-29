"""Parse une page Visualforce (.page) en arbre de VfNode."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class VfNode:
    """Nœud de l'arbre VF (un composant apex:xxx)."""
    tag: str              # "page", "pageBlock", etc. (sans préfixe)
    attributes: dict      # clés normalisées en lowercase
    children: list        # list[VfNode | str]


def _strip_prefix(tag: str) -> str:
    """Retire les préfixes XML (apex:, c:, flow:, etc.)."""
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def _build_node(elem: ET.Element) -> VfNode:
    """Convertit récursivement un Element XML en VfNode."""
    tag = _strip_prefix(elem.tag)
    attrs = {k.lower(): v for k, v in elem.attrib.items()}
    children: list[VfNode | str] = []

    # Texte avant le premier enfant
    if elem.text and elem.text.strip():
        children.append(elem.text)

    for child in elem:
        children.append(_build_node(child))
        # Texte après chaque enfant (tail)
        if child.tail and child.tail.strip():
            children.append(child.tail)

    return VfNode(tag=tag, attributes=attrs, children=children)


_FAKE_NS = (
    ' xmlns:apex="urn:apex" xmlns:c="urn:c"'
    ' xmlns:flow="urn:flow" xmlns:html="http://www.w3.org/1999/xhtml"'
)


def _strip_ns_uri(tag: str) -> str:
    """Retire le namespace URI {urn:apex}page → apex:page, puis le préfixe."""
    m = re.match(r'\{urn:(\w+)\}(.+)', tag)
    if m:
        return m.group(2)  # on retourne juste le local name
    # Namespace standard {http://...}tag
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _build_node_ns(elem: ET.Element) -> VfNode:
    """Convertit un Element XML (avec namespaces) en VfNode."""
    tag = _strip_ns_uri(elem.tag)
    attrs = {k.lower(): v for k, v in elem.attrib.items()}
    children: list[VfNode | str] = []

    if elem.text and elem.text.strip():
        children.append(elem.text)

    for child in elem:
        children.append(_build_node_ns(child))
        if child.tail and child.tail.strip():
            children.append(child.tail)

    return VfNode(tag=tag, attributes=attrs, children=children)


def parse_vf_page(path: str) -> VfNode:
    """Parse un fichier .page et retourne la racine VfNode."""
    with open(path) as f:
        content = f.read()

    content = content.replace("&nbsp;", " ")
    # Échapper les & non suivis d'une entité XML connue
    content = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#)', '&amp;', content)

    # Injecter les déclarations de namespace manquantes dans la balise racine
    # pour que le parser XML standard les accepte.
    content = re.sub(
        r'<(apex:page)\b',
        r'<\1' + _FAKE_NS,
        content,
        count=1,
    )

    root = ET.fromstring(content)
    return _build_node_ns(root)
