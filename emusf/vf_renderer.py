"""Rendu HTML SLDS d'un arbre Visualforce."""

from __future__ import annotations

from markupsafe import Markup, escape

from .vf_parser import VfNode
from .vf_controller import VfPageContext
from .vf_expression import resolve, resolve_text


class VfRenderer:
    """Convertit un arbre VfNode en HTML SLDS."""

    def __init__(self, context: VfPageContext, page_name: str):
        self.ctx = context
        self.page_name = page_name
        self.loop_vars: dict = {}

    # --- public API ---

    def render(self) -> str:
        return self._render_node(self.ctx.page_node)

    # --- dispatch ---

    def _render_node(self, node) -> str:
        if isinstance(node, str):
            return self._resolve_text(node)

        # Attribut rendered="{!expr}" — rendu conditionnel
        if isinstance(node, VfNode) and "rendered" in node.attributes:
            rendered = node.attributes["rendered"]
            if rendered.startswith("{!"):
                val = self._resolve_expr(rendered)
                if not val:
                    return ""
            elif rendered.lower() == "false":
                return ""

        handler = getattr(self, "_render_" + node.tag, None)
        if handler:
            return handler(node)
        return self._render_default(node)

    def _render_children(self, node: VfNode) -> str:
        return "".join(self._render_node(c) for c in node.children)

    def _render_children_skip_facets(self, node: VfNode) -> str:
        """Rend les enfants en ignorant les <apex:facet>."""
        return "".join(
            self._render_node(c) for c in node.children
            if not (isinstance(c, VfNode) and c.tag == "facet")
        )

    def _get_facet(self, node: VfNode, name: str) -> VfNode | None:
        """Cherche un <apex:facet name="xxx"> parmi les enfants."""
        for c in node.children:
            if isinstance(c, VfNode) and c.tag == "facet" and c.attributes.get("name") == name:
                return c
        return None

    # --- page structure ---

    def _render_page(self, node: VfNode) -> str:
        return self._render_children(node)

    def _render_html(self, node: VfNode) -> str:
        return self._render_children(node)

    def _render_head(self, node: VfNode) -> str:
        return ""  # CSS géré par base.html

    def _render_body(self, node: VfNode) -> str:
        return self._render_children(node)

    def _render_slds(self, node: VfNode) -> str:
        return ""

    # --- form ---

    def _render_form(self, node: VfNode) -> str:
        inner = self._render_children(node)
        return '<form method="POST" action="/apex/{}">{}</form>'.format(
            escape(self.page_name), inner
        )

    # --- page blocks ---

    def _render_pageBlock(self, node: VfNode) -> str:
        title = node.attributes.get("title", "")
        title = self._resolve_text(title)
        inner = self._render_children(node)
        header = ""
        if title:
            header = (
                '<div class="slds-card__header slds-grid">'
                '<header class="slds-media slds-media_center slds-has-flexi-truncate">'
                '<div class="slds-media__body">'
                '<h2 class="slds-card__header-title">'
                '<span>{}</span>'
                '</h2></div></header></div>'
            ).format(escape(title))
        return '<div class="slds-card">{}<div class="slds-card__body slds-card__body_inner">{}</div></div>'.format(
            header, inner
        )

    def _render_pageBlockSection(self, node: VfNode) -> str:
        title = node.attributes.get("title", "")
        title = self._resolve_text(title)
        columns = node.attributes.get("columns", "2")
        inner = self._render_children(node)
        header = ""
        if title:
            header = '<h3 class="slds-section__title slds-theme_shade"><span class="slds-truncate slds-p-horizontal_small">{}</span></h3>'.format(
                escape(title)
            )
        return '<div class="slds-section slds-is-open">{}<div class="slds-section__content slds-grid slds-wrap slds-gutters">{}</div></div>'.format(
            header, inner
        )

    def _render_pageBlockSectionItem(self, node: VfNode) -> str:
        inner = self._render_children(node)
        return '<div class="slds-col slds-size_1-of-2 slds-p-around_x-small">{}</div>'.format(inner)

    def _render_pageBlockButtons(self, node: VfNode) -> str:
        inner = self._render_children(node)
        return '<div class="slds-card__footer">{}</div>'.format(inner)

    # --- messages ---

    def _render_pageMessages(self, node: VfNode) -> str:
        if not self.ctx.messages:
            return ""
        html_parts = []
        for msg in self.ctx.messages:
            severity = msg.get("severity", "ERROR") if isinstance(msg, dict) else "ERROR"
            summary = msg.get("summary", str(msg)) if isinstance(msg, dict) else str(msg)
            theme = {
                "CONFIRM": "success", "INFO": "info",
                "WARNING": "warning", "ERROR": "error",
            }.get(str(severity).upper(), "error")
            html_parts.append(
                '<div class="slds-notify slds-notify_alert slds-alert_{}" role="alert">'
                '<span class="slds-assistive-text">{}</span>'
                '<h2>{}</h2></div>'.format(theme, escape(severity), escape(summary))
            )
        return '<div class="slds-notify_container slds-notify_container_inline">{}</div>'.format(
            "".join(html_parts)
        )

    # --- buttons & actions ---

    def _render_commandButton(self, node: VfNode) -> str:
        value = node.attributes.get("value", "Submit")
        action = node.attributes.get("action", "")
        style_class = node.attributes.get("styleclass", "slds-button slds-button_brand")
        action_name = ""
        if action.startswith("{!") and action.endswith("}"):
            action_name = action[2:-1].strip()
        return (
            '<button type="submit" name="__vf_action__" value="{}" '
            'class="{}">{}</button>'
        ).format(escape(action_name), escape(style_class), escape(value))

    def _render_commandLink(self, node: VfNode) -> str:
        action = node.attributes.get("action", "")
        value = node.attributes.get("value", "")
        inner = self._render_children(node)
        action_name = ""
        if action.startswith("{!") and action.endswith("}"):
            action_name = action[2:-1].strip()
        text = inner or escape(value)
        return (
            '<button type="submit" name="__vf_action__" value="{}" '
            'class="slds-button slds-button_neutral">{}</button>'
        ).format(escape(action_name), text)

    # --- tables ---

    def _render_pageBlockTable(self, node: VfNode) -> str:
        return self._render_table(node)

    def _render_dataTable(self, node: VfNode) -> str:
        return self._render_table(node)

    def _render_table(self, node: VfNode) -> str:
        value_expr = node.attributes.get("value", "")
        var_name = node.attributes.get("var", "item")
        items = self._resolve_expr(value_expr)
        if not isinstance(items, (list, tuple)):
            items = []

        columns = [c for c in node.children if isinstance(c, VfNode) and c.tag == "column"]

        # Header
        html = '<table class="slds-table slds-table_cell-buffer slds-table_bordered">'
        html += '<thead><tr class="slds-line-height_reset">'
        for col in columns:
            header = col.attributes.get("headervalue", "")
            # Chercher un <apex:facet name="header">
            if not header:
                facet = self._get_facet(col, "header")
                if facet:
                    header = self._render_children(facet)
                elif "value" in col.attributes:
                    header = col.attributes["value"].replace("{!", "").replace("}", "")
                    header = header.split(".")[-1]
            html += '<th scope="col"><div class="slds-truncate">{}</div></th>'.format(
                header if "<" in header else escape(header)
            )
        html += '</tr></thead><tbody>'

        # Rows
        for item in items:
            self.loop_vars[var_name] = item
            html += '<tr class="slds-hint-parent">'
            for col in columns:
                if not self._is_rendered(col):
                    continue
                if "value" in col.attributes and not self._has_child_content(col):
                    cell_val = self._resolve_expr(col.attributes["value"])
                    html += '<td><div class="slds-truncate">{}</div></td>'.format(
                        escape(str(cell_val)) if cell_val is not None else ""
                    )
                else:
                    cell_html = self._render_children_skip_facets(col)
                    html += '<td>{}</td>'.format(cell_html)
            html += '</tr>'

        if var_name in self.loop_vars:
            del self.loop_vars[var_name]

        html += '</tbody></table>'
        return html

    def _render_column(self, node: VfNode) -> str:
        if "value" in node.attributes:
            val = self._resolve_expr(node.attributes["value"])
            return str(val) if val is not None else ""
        return self._render_children(node)

    def _render_facet(self, node: VfNode) -> str:
        # Normalement géré par le parent, mais fallback
        return self._render_children(node)

    # --- repeat ---

    def _render_repeat(self, node: VfNode) -> str:
        value_expr = node.attributes.get("value", "")
        var_name = node.attributes.get("var", "item")
        items = self._resolve_expr(value_expr)
        if not isinstance(items, (list, tuple)):
            items = []
        html = ""
        for item in items:
            self.loop_vars[var_name] = item
            html += self._render_children(node)
        if var_name in self.loop_vars:
            del self.loop_vars[var_name]
        return html

    # --- output ---

    def _render_outputText(self, node: VfNode) -> str:
        value = node.attributes.get("value", "")
        resolved = self._resolve_text(value) if value else ""
        inner = self._render_children(node)
        style_class = node.attributes.get("styleclass", "")
        cls = ' class="{}"'.format(escape(style_class)) if style_class else ""
        return '<span{}>{}{}</span>'.format(cls, escape(resolved), inner)

    def _render_outputLink(self, node: VfNode) -> str:
        href = node.attributes.get("value", "#")
        href = self._resolve_text(href)
        target = node.attributes.get("target", "")
        inner = self._render_children(node)
        target_attr = ' target="{}"'.format(escape(target)) if target else ""
        return '<a href="{}"{}>{}</a>'.format(escape(href), target_attr, inner)

    def _render_outputField(self, node: VfNode) -> str:
        value = node.attributes.get("value", "")
        label = node.attributes.get("label", "")
        resolved = self._resolve_expr(value)
        if not label:
            label = value.replace("{!", "").replace("}", "").split(".")[-1]
        return (
            '<div class="slds-form-element">'
            '<span class="slds-form-element__label">{}</span>'
            '<div class="slds-form-element__static">{}</div>'
            '</div>'
        ).format(escape(label), escape(str(resolved)) if resolved is not None else "")

    def _render_outputPanel(self, node: VfNode) -> str:
        inner = self._render_children(node)
        layout = node.attributes.get("layout", "")
        if layout == "block":
            return '<div>{}</div>'.format(inner)
        return '<span>{}</span>'.format(inner)

    def _render_outputLabel(self, node: VfNode) -> str:
        value = node.attributes.get("value", "")
        value = self._resolve_text(value)
        inner = self._render_children(node)
        return '<label class="slds-form-element__label">{}{}</label>'.format(
            escape(value), inner
        )

    # --- input ---

    def _render_inputField(self, node: VfNode) -> str:
        value_expr = node.attributes.get("value", "")
        label = node.attributes.get("label", "")
        field_name = value_expr.replace("{!", "").replace("}", "").split(".")[-1]
        if not label:
            label = field_name
        current_val = self._resolve_expr(value_expr)
        return (
            '<div class="slds-form-element">'
            '<label class="slds-form-element__label">{}</label>'
            '<div class="slds-form-element__control">'
            '<input type="text" name="{}" value="{}" class="slds-input"/>'
            '</div></div>'
        ).format(escape(label), escape(field_name),
                 escape(str(current_val)) if current_val else "")

    def _render_inputText(self, node: VfNode) -> str:
        value_expr = node.attributes.get("value", "")
        label = node.attributes.get("label", "")
        current_val = self._resolve_expr(value_expr) or ""
        name = value_expr.replace("{!", "").replace("}", "").replace(".", "_")
        return (
            '<div class="slds-form-element">'
            '<label class="slds-form-element__label">{}</label>'
            '<div class="slds-form-element__control">'
            '<input type="text" name="{}" value="{}" class="slds-input"/>'
            '</div></div>'
        ).format(escape(label), escape(name), escape(str(current_val)))

    def _render_inputCheckbox(self, node: VfNode) -> str:
        value_expr = node.attributes.get("value", "")
        label = node.attributes.get("label", "")
        current_val = self._resolve_expr(value_expr)
        name = value_expr.replace("{!", "").replace("}", "").replace(".", "_")
        checked = " checked" if current_val else ""
        return (
            '<div class="slds-form-element">'
            '<div class="slds-form-element__control">'
            '<label class="slds-checkbox">'
            '<input type="checkbox" name="{}"{}>'
            '<span class="slds-checkbox_faux"></span>'
            '<span class="slds-form-element__label">{}</span>'
            '</label></div></div>'
        ).format(escape(name), checked, escape(label))

    def _render_input(self, node: VfNode) -> str:
        value_expr = node.attributes.get("value", "")
        label = node.attributes.get("label", "")
        title = node.attributes.get("title", label)
        placeholder = node.attributes.get("html-placeholder", "")
        current_val = self._resolve_expr(value_expr) or ""
        name = value_expr.replace("{!", "").replace("}", "").replace(".", "_")
        required = ' required' if node.attributes.get("required") == "true" else ""
        return (
            '<div class="slds-form-element">'
            '<label class="slds-form-element__label">{}</label>'
            '<div class="slds-form-element__control">'
            '<input type="text" name="{}" value="{}" placeholder="{}" '
            'class="slds-input" title="{}"{}/>'
            '</div></div>'
        ).format(escape(label), escape(name), escape(str(current_val)),
                 escape(placeholder), escape(title), required)

    def _render_inputHidden(self, node: VfNode) -> str:
        value_expr = node.attributes.get("value", "")
        current_val = self._resolve_expr(value_expr) or ""
        name = value_expr.replace("{!", "").replace("}", "").replace(".", "_")
        return '<input type="hidden" name="{}" value="{}"/>'.format(
            escape(name), escape(str(current_val))
        )

    def _render_selectList(self, node: VfNode) -> str:
        value_expr = node.attributes.get("value", "")
        current_val = self._resolve_expr(value_expr) or ""
        name = value_expr.replace("{!", "").replace("}", "").replace(".", "_")
        inner = self._render_children(node)
        return (
            '<div class="slds-form-element"><div class="slds-form-element__control">'
            '<div class="slds-select_container">'
            '<select name="{}" class="slds-select">{}</select>'
            '</div></div></div>'
        ).format(escape(name), inner)

    def _render_selectOptions(self, node: VfNode) -> str:
        # Les options viennent normalement du controller — pas encore supporté
        return '<option value="">--</option>'

    # --- iframe ---

    def _render_iframe(self, node: VfNode) -> str:
        src = node.attributes.get("src", "")
        src = self._resolve_text(src)
        width = node.attributes.get("width", "100%")
        height = node.attributes.get("height", "600px")
        return '<iframe src="{}" width="{}" height="{}" frameborder="0"></iframe>'.format(
            escape(src), escape(width), escape(height)
        )

    # --- action / status (stubs) ---

    def _render_actionFunction(self, node: VfNode) -> str:
        return ""  # JavaScript-side — pas de rendu

    def _render_actionStatus(self, node: VfNode) -> str:
        # Rendre le facet "stop" (état par défaut)
        stop_facet = self._get_facet(node, "stop")
        if stop_facet:
            return self._render_children(stop_facet)
        return self._render_children(node)

    def _render_param(self, node: VfNode) -> str:
        return ""  # Paramètre pour le parent, pas de rendu

    # --- default / fallback ---

    def _render_default(self, node: VfNode) -> str:
        """Fallback : rend les enfants sans wrapper."""
        return self._render_children(node)

    # --- helpers ---

    def _resolve_expr(self, value: str):
        """Résout une expression {!...} complète."""
        if not value:
            return None
        value = value.strip()
        if value.startswith("{!") and value.endswith("}"):
            expr = value[2:-1].strip()
            return resolve(expr, self.ctx.record, self.ctx.instance_vars,
                           self.loop_vars, self.ctx.org)
        return value

    def _resolve_text(self, text: str) -> str:
        """Résout les expressions {!...} inline dans du texte."""
        if "{!" not in text:
            return text
        return resolve_text(text, self.ctx.record, self.ctx.instance_vars,
                            self.loop_vars, self.ctx.org)

    def _is_rendered(self, node: VfNode) -> bool:
        """Vérifie l'attribut rendered."""
        rendered = node.attributes.get("rendered", "true")
        if rendered.startswith("{!"):
            val = self._resolve_expr(rendered)
            return bool(val)
        return rendered.lower() != "false"

    def _has_child_content(self, node: VfNode) -> bool:
        """Vérifie si un nœud a des enfants significatifs (pas juste des facets)."""
        for c in node.children:
            if isinstance(c, str):
                return True
            if isinstance(c, VfNode) and c.tag != "facet":
                return True
        return False
