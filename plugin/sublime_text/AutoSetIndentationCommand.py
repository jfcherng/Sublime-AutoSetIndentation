import collections
import editorconfig
import IndentFinder.indent_finder as indentfinder
import re
import sublime
import sublime_plugin
from typing import List
from ..log import msg, show_status_message
from ..settings import get_setting

Indentation = collections.namedtuple("Indentation", ["type", "size"])
INDENTATION_UNKNOWN = Indentation("unknown", -1)


def get_ASI_result_sources_for_view(view: sublime.View) -> List[str]:
    return view.settings().get("ASI_result_sources", [])  # type: ignore


def reset_ASI_result_sources_for_view(view: sublime.View) -> None:
    view.settings().set("ASI_result_sources", [])


def add_ASI_result_sources_for_view(view: sublime.View, sources: List[str]) -> None:
    view.settings().set("ASI_result_sources", get_ASI_result_sources_for_view(view) + list(sources))


def merge_indentation_tuples(base: Indentation, spare: Indentation) -> Indentation:
    merged = base._asdict()

    if merged["type"] == INDENTATION_UNKNOWN.type:
        merged["type"] = spare.type

    if merged["size"] == INDENTATION_UNKNOWN.size:
        merged["size"] = spare.size

    return Indentation(**merged)


class AutoSetIndentationCommand(sublime_plugin.TextCommand):
    """ Examines the contents of the buffer to determine the indentation settings. """

    def run(self, edit: sublime.Edit, show_message: bool = True, sample_length: int = 2 ** 16) -> None:
        """
        @brief Run the "auto_set_indentation" command.

        @param self         The object
        @param edit         The edit
        @param show_message The show message
        """

        reset_ASI_result_sources_for_view(self.view)

        indent = self.get_indentation_for_view(self.view, sample_length)

        # if a special indentation case is met, there is no need to run more codes
        if self.special_indentation_cases(self.view, indent, show_message):
            return

        # unable to determine, use the default settings
        if indent.type == INDENTATION_UNKNOWN.type or indent.size <= 0:
            reset_ASI_result_sources_for_view(self.view)
            self.use_indentation_default(self.view, show_message)
            return

        # tab-indented
        if indent.type == "tab":
            self.use_indentation_tab(self.view, indent.size, show_message)
            return

        # space-indented
        if indent.type == "space":
            self.use_indentation_space(self.view, indent.size, show_message)
            return

    def special_indentation_cases(self, view: sublime.View, indent: Indentation, show_message: bool = True) -> bool:
        """
        @brief Handle some special indentation cases.

        @param self         The object
        @param indent       The indent
        @param show_message The show message

        @return True if the  indentation has been set during execution, False otherwise.
        """

        default_indentation = get_setting("default_indentation")
        indent_size = indent.size if indent.size >= 0 else default_indentation[1]

        # makefile only accepts tab indentation
        if view.match_selector(0, "source.makefile"):
            add_ASI_result_sources_for_view(view, ["special"])
            self.use_indentation_tab(view, indent_size, show_message)

            return True

        return False

    def get_indentation_for_view(self, view: sublime.View, sample_length: int = 2 ** 16) -> Indentation:
        """
        @brief Guess the indentation for the view.
               This would first try using configs from the .editorconfig file
               and guess the indentation as the fallback otherwise.

        @param self          The object
        @param view          The view
        @param sample_length The sample length

        @return The indentation namedtuple for view.
        """

        indentation_editorconfig = self.get_indentation_from_editorconfig()

        if indentation_editorconfig != INDENTATION_UNKNOWN:
            add_ASI_result_sources_for_view(view, [".editorconfig"])

        # .editorconfig provides all needed informations
        if (
            indentation_editorconfig.type != INDENTATION_UNKNOWN.type
            and indentation_editorconfig.size != INDENTATION_UNKNOWN.size
        ):
            return indentation_editorconfig

        sample = view.substr(sublime.Region(0, min(len(view), sample_length)))
        indentation_guessed = self.guess_indentation_from_string(sample)

        add_ASI_result_sources_for_view(view, ["guessing"])

        return merge_indentation_tuples(indentation_editorconfig, indentation_guessed)

    def get_indentation_from_editorconfig(self) -> Indentation:
        """
        @brief Guess the indentation from the .editorconfig file.

        @param self   The object

        @return Indentation namedtuple
        """

        indentation = INDENTATION_UNKNOWN._asdict()

        file_path = self.view.file_name()

        # is a new buffer so no file path
        if not file_path:
            return INDENTATION_UNKNOWN

        try:
            options = editorconfig.get_properties(file_path)
        except editorconfig.EditorConfigError:
            return INDENTATION_UNKNOWN

        indent_style = options.get("indent_style")
        indent_size = options.get("indent_size")

        # sanitize indent_style
        if indent_style != "space" and indent_style != "tab":
            indent_style = INDENTATION_UNKNOWN.type

        # sanitize indent_size
        try:
            indent_size = int(indent_size)
        except (TypeError, ValueError):
            indent_size = INDENTATION_UNKNOWN.size

        if indent_style == "space" or indent_style == "tab":
            indentation["type"] = indent_style
            indentation["size"] = indent_size

            return Indentation(**indentation)

        return INDENTATION_UNKNOWN

    def guess_indentation_from_string(self, string: str) -> Indentation:
        """
        @brief Guess the indentation of the given string.

        @param self   The object
        @param string The string

        @return Indentation namedtuple
        """

        indentation = INDENTATION_UNKNOWN._asdict()

        indent_finder = indentfinder.IndentFinder(tuple(INDENTATION_UNKNOWN))
        indent_finder.parse_string(string)

        # possible outputs:
        #   - space X
        #   - tab Y
        #   - mixed tab Y space X
        #   - unknown -1 (the default one from the constructor)
        finder_result = str(indent_finder)

        # unable to determine the indentation
        if finder_result == "{type} {size}".format_map(INDENTATION_UNKNOWN._asdict()):
            return INDENTATION_UNKNOWN

        indent_tab_m = re.search(r"\btab\s+(?P<size>[0-9]+)", finder_result)
        indent_tab = int(indent_tab_m.group("size")) if indent_tab_m else 0

        indent_space_m = re.search(r"\bspace\s+(?P<size>[0-9]+)", finder_result)
        indent_space = int(indent_space_m.group("size")) if indent_space_m else 0

        # note that for mixed indentation, we assume it's tab-indented
        if indent_tab > 0:
            indentation["type"] = "tab"
            indentation["size"] = indent_tab

        if indent_space > 0:
            indentation["type"] = "space"
            indentation["size"] = indent_space

        return Indentation(**indentation)

    def use_indentation_default(self, view: sublime.View, show_message: bool = True) -> None:
        """
        @brief Sets the indentation to default.

        @param self                The object
        @param view                The view
        @param show_message        The show message
        """

        indent_type, indent_size = get_setting("default_indentation")
        indent_type = indent_type.lower()

        if indent_type.startswith("tab"):
            self.use_indentation_tab(view, indent_size, False)

        if indent_type.startswith("space"):
            self.use_indentation_space(view, indent_size, False)

        show_status_message(msg("Indentation: {}/{} (default)".format(indent_type, indent_size)), show_message)

    def use_indentation_tab(self, view: sublime.View, indent_tab: int = 4, show_message: bool = True) -> None:
        """
        @brief Sets the indentation to tab.

        @param self         The object
        @param view         The view
        @param indent_tab   The indent tab size
        @param show_message The show message
        """

        self.view.settings().set("translate_tabs_to_spaces", False)
        self.view.settings().set("tab_size", indent_tab)

        show_status_message(
            msg("Indentation: tab/{} (by {})".format(indent_tab, ", ".join(get_ASI_result_sources_for_view(view)))),
            show_message,
        )

    def use_indentation_space(self, view: sublime.View, indent_space: int = 4, show_message: bool = True) -> None:
        """
        @brief Sets the indentation to space.

        @param self         The object
        @param view         The view
        @param indent_space The indent space size
        @param show_message The show message
        """

        self.view.settings().set("translate_tabs_to_spaces", True)
        self.view.settings().set("tab_size", indent_space)

        show_status_message(
            msg("Indentation: space/{} (by {})".format(indent_space, ", ".join(get_ASI_result_sources_for_view(view)))),
            show_message,
        )
