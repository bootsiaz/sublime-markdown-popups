# -*- coding: utf-8 -*-
"""
Markdown popup.

Markdown tooltips and phantoms for SublimeText.

TextMate theme to CSS.

https://manual.macromates.com/en/language_grammars#naming_conventions
"""
import sublime
import markdown
import traceback
import time
from . import colorbox
from collections import OrderedDict
from .st_scheme_template import Scheme2CSS, POPUP, PHANTOM
from .st_clean_css import clean_css
from .st_pygments_highlight import syntax_hl as pyg_syntax_hl
from .st_code_highlight import SublimeHighlight
from .st_mapping import lang_map
from . import imagetint
import re
import os

version_info = (1, 8, 1)
__version__ = '.'.join([str(x) for x in version_info])

PHANTOM_SUPPORT = int(sublime.version()) >= 3118
BASE_CSS = 'Packages/mdpopups/css/base.css'
DEFAULT_CSS = 'Packages/mdpopups/css/default.css'
DEFAULT_USER_CSS = 'Packages/User/mdpopups.css'
base_css = None
IDK = '''
<style>html {background-color: #333; color: red}</style>
<div><p>¯\_(ツ)_/¯'</p></div>
'''
RE_BAD_ENTITIES = re.compile(r'(&(?!amp;|lt;|gt;|nbsp;)(?:\w+;|#\d+;))')

NODEBUG = 0
ERROR = 1
WARNING = 2
INFO = 3


def _log(msg):
    """Log."""

    print('mdpopups: %s' % str(msg))


def _debug(msg, level):
    """Debug log."""

    if int(_get_setting('mdpopups.debug', NODEBUG)) >= level:
        _log(msg)


def _get_setting(name, default=None):
    """Get the Sublime setting."""

    return sublime.load_settings('Preferences.sublime-settings').get(name, default)


def _can_show(view, location=-1):
    """
    Check if popup can be shown.

    I have seen Sublime can sometimes crash if trying
    to do a popup off screen.  Normally it should just not show,
    but sometimes it can crash.  We will check if popup
    can/should be attempted.
    """

    can_show = True
    sel = view.sel()
    if location >= 0:
        region = view.visible_region()
        if region.begin() > location or region.end() < location:
            can_show = False
    elif len(sel) >= 1:
        region = view.visible_region()
        if region.begin() > sel[0].b or region.end() < sel[0].b:
            can_show = False
    else:
        can_show = False

    return can_show

##############################
# Theme/Scheme cache management
##############################
_scheme_cache = OrderedDict()
_highlighter_cache = OrderedDict()


def _clear_cache():
    """Clear the css cache."""

    global _scheme_cache
    global _highlighter_cache
    global base_css
    base_css = None
    _scheme_cache = OrderedDict()
    _highlighter_cache = OrderedDict()


def _is_cache_expired(cache_time):
    """Check if the cache entry is expired."""

    delta_time = _get_setting('mdpopups.cache_refresh_time', 30)
    if not isinstance(delta_time, int) or delta_time < 0:
        delta_time = 30
    return delta_time == 0 or (time.time() - cache_time) >= (delta_time * 60)


def _prune_cache():
    """Prune older items in cache (related to when they were inserted)."""

    limit = _get_setting('mdpopups.cache_limit', 10)
    if limit is None or not isinstance(limit, int) or limit <= 0:
        limit = 10
    while len(_scheme_cache) >= limit:
        _scheme_cache.popitem(last=True)
    while len(_highlighter_cache) >= limit:
        _highlighter_cache.popitem(last=True)


def _get_sublime_highlighter(view):
    """Get the SublimeHighlighter."""

    scheme = view.settings().get('color_scheme')
    obj = None
    if scheme is not None:
        if scheme in _highlighter_cache:
            obj, t = _highlighter_cache[scheme]
            if _is_cache_expired(t):
                obj = None
        if obj is None:
            try:
                obj = SublimeHighlight(scheme)
                _prune_cache()
                _highlighter_cache[scheme] = (obj, time.time())
            except Exception:
                _log('Failed to get Sublime highlighter object!')
                _debug(traceback.format_exc(), ERROR)
                pass
    return obj


def _get_scheme(view):
    """Get the scheme object and user CSS."""

    scheme = view.settings().get('color_scheme')
    settings = sublime.load_settings("Preferences.sublime-settings")
    obj = None
    user_css = ''
    if scheme is not None:
        if scheme in _scheme_cache:
            obj, user_css, t = _scheme_cache[scheme]
            # Check if cache expired or user changed pygments setting.
            if (
                _is_cache_expired(t) or
                obj.variables.get('use_pygments', True) != (not settings.get('mdpopups.use_sublime_highlighter', False))
            ):
                obj = None
                user_css = ''
        if obj is None:
            try:
                obj = Scheme2CSS(scheme)
                _prune_cache()
                user_css = _get_user_css()
                _scheme_cache[scheme] = (obj, user_css, time.time())
            except Exception:
                _log('Failed to convert/retrieve scheme to CSS!')
                _debug(traceback.format_exc(), ERROR)
    return obj, user_css


def _get_user_css():
    """Get user css."""

    css = None

    user_css = _get_setting('mdpopups.user_css', DEFAULT_USER_CSS)
    try:
        css = clean_css(sublime.load_resource(user_css))
    except Exception:
        css = clean_css(sublime.load_resource(DEFAULT_CSS))
    return css if css else ''


##############################
# Markdown parsing
##############################
class _MdWrapper(markdown.Markdown):
    """
    Wrapper around Python Markdown's class.

    This allows us to gracefully continue when a module doesn't load.
    """

    Meta = {}

    def __init__(self, *args, **kwargs):
        """Call original init."""

        super(_MdWrapper, self).__init__(*args, **kwargs)

    def registerExtensions(self, extensions, configs):  # noqa
        """
        Register extensions with this instance of Markdown.

        Keyword arguments:

        * extensions: A list of extensions, which can either
           be strings or objects.  See the docstring on Markdown.
        * configs: A dictionary mapping module names to config options.

        """

        from markdown import util
        from markdown.extensions import Extension

        for ext in extensions:
            try:
                if isinstance(ext, util.string_type):
                    ext = self.build_extension(ext, configs.get(ext, {}))
                if isinstance(ext, Extension):
                    ext.extendMarkdown(self, globals())
                elif ext is not None:
                    raise TypeError(
                        'Extension "%s.%s" must be of type: "markdown.Extension"'
                        % (ext.__class__.__module__, ext.__class__.__name__)
                    )
            except Exception:
                # We want to gracefully continue even if an extension fails.
                _log('Failed to load markdown module!')
                _debug(traceback.format_exc(), ERROR)

        return self


def _get_theme(view, css=None, css_type=POPUP):
    """Get the theme."""

    global base_css
    if base_css is None:
        base_css = clean_css(sublime.load_resource(BASE_CSS))
    obj, user_css = _get_scheme(view)
    font_size = view.settings().get('font_size', 12)
    try:
        return obj.apply_template(
            base_css +
            obj.get_css() +
            (css if css else '') +
            user_css,
            css_type,
            font_size
        ) if obj is not None else ''
    except Exception:
        _log('Failed to retrieve scheme CSS!')
        _debug(traceback.format_exc(), ERROR)
        return ''


def _remove_entities(text):
    """Remove unsupported HTML entities."""

    import html.parser
    html = html.parser.HTMLParser()

    def repl(m):
        """Replace entites except &, <, >, and nbsp."""
        return html.unescape(m.group(1))

    return RE_BAD_ENTITIES.sub(repl, text)


def _create_html(view, content, md=True, css=None, debug=False, css_type=POPUP, nl2br=True):
    """Create html from content."""

    debug = _get_setting('mdpopups.debug', NODEBUG)
    if debug:
        _debug('=====Content=====', INFO)
        _debug(content, INFO)

    if css is None or not isinstance(css, str):
        css = ''

    style = _get_theme(view, css, css_type)

    if debug:
        _debug('=====CSS=====', INFO)
        _debug(style, INFO)

    if md:
        content = md2html(view, content, nl2br=nl2br)

    if debug:
        _debug('=====HTML OUTPUT=====', INFO)
        _debug(content, INFO)

    html = "<style>%s</style>" % (style)
    html += _remove_entities(content)
    return html


##############################
# Public functions
##############################
def version():
    """Get the current version."""

    return version_info


def md2html(view, markup, nl2br=True):
    """Convert Markdown to HTML."""

    if _get_setting('mdpopups.use_sublime_highlighter'):
        sublime_hl = (True, _get_sublime_highlighter(view))
    else:
        sublime_hl = (False, None)

    extensions = [
        "markdown.extensions.attr_list",
        "markdown.extensions.codehilite",
        "mdpopups.mdx.superfences",
        "mdpopups.mdx.betterem",
        "mdpopups.mdx.magiclink",
        "mdpopups.mdx.inlinehilite",
        "markdown.extensions.admonition",
        "markdown.extensions.def_list"
    ]

    if nl2br:
        extensions.append('markdown.extensions.nl2br')

    configs = {
        "mdpopups.mdx.inlinehilite": {
            "style_plain_text": True,
            "css_class": "inline-highlight",
            "use_codehilite_settings": False,
            "guess_lang": False,
            "sublime_hl": sublime_hl
        },
        "markdown.extensions.codehilite": {
            "guess_lang": False,
            "css_class": "highlight"
        },
        "mdpopups.mdx.superfences": {
            "uml_flow": False,
            "uml_sequence": False,
            "sublime_hl": sublime_hl
        }
    }

    return _MdWrapper(
        extensions=extensions,
        extension_configs=configs
    ).convert(markup).replace('&quot;', '"').replace('\n', '')


def color_box(
    colors, border="#000000ff", border2=None, height=32, width=32,
    border_size=1, check_size=4, max_colors=5, alpha=False, border_map=0xF
):
    """Color box."""

    return colorbox.color_box(
        colors, border, border2, height, width,
        border_size, check_size, max_colors, alpha, border_map
    )


def color_box_raw(
    colors, border="#000000ff", border2=None, height=32, width=32,
    border_size=1, check_size=4, max_colors=5, alpha=False, border_map=0xF
):
    """Color box raw."""

    return colorbox.color_box_raw(
        colors, border, border2, height, width,
        border_size, check_size, max_colors, alpha, border_map
    )


def tint(img, color, opacity=255, height=None, width=None):
    """Tint the image."""

    if isinstance(img, str):
        try:
            img = sublime.load_binary_resource(img)
        except Exception:
            _log('Could not open binary file!')
            _debug(traceback.format_exc(), ERROR)
            return ''
    return imagetint.tint(img, color, opacity, height, width)


def tint_raw(img, color, opacity=255):
    """Tint the image."""

    if isinstance(img, str):
        try:
            img = sublime.load_binary_resource(img)
        except Exception:
            _log('Could not open binary file!')
            _debug(traceback.format_exc(), ERROR)
            return ''
    return imagetint.tint_raw(img, color, opacity)


def get_language_from_view(view):
    """Guess current language from view."""

    lang = None
    user_map = sublime.load_settings('Preferences.sublime-settings').get('mdpopups.sublime_user_lang_map', {})
    syntax = os.path.splitext(view.settings().get('syntax').replace('Packages/', '', 1))[0]
    keys = set(list(lang_map.keys()) + list(user_map.keys()))
    for key in keys:
        v1 = lang_map.get(key, (tuple(), tuple()))[1]
        v2 = user_map.get(key, (tuple(), tuple()))[1]
        if syntax in (tuple(v2) + v1):
            lang = key
            break
    return lang


def syntax_highlight(view, src, language=None, inline=False):
    """Syntax highlighting for code."""

    try:
        if _get_setting('mdpopups.use_sublime_highlighter'):
            highlighter = _get_sublime_highlighter(view)
            code = highlighter.syntax_highlight(src, language, inline=inline)
        else:
            code = pyg_syntax_hl(src, language, inline=inline)
    except Exception:
        code = src
        _log('Failed to highlight code!')
        _debug(traceback.format_exc(), ERROR)

    return code


def scope2style(view, scope, selected=False, explicit_background=False):
    """Convert the scope to a style."""

    style = {
        'color': None,
        'background': None,
        'style': ''
    }
    obj = _get_scheme(view)[0]
    style_obj = obj.guess_style(scope, selected, explicit_background)
    style['color'] = style_obj.fg_simulated
    style['background'] = style_obj.bg_simulated
    style['style'] = style_obj.style
    return style


def clear_cache():
    """Clear cache."""

    _clear_cache()


def hide_popup(view):
    """Hide the popup."""

    view.hide_popup()


def update_popup(view, content, md=True, css=None, nl2br=True):
    """Update the popup."""

    disabled = _get_setting('mdpopups.disable', False)
    if disabled:
        _debug('Popups disabled', WARNING)
        return

    try:
        html = _create_html(view, content, md, css, css_type=POPUP, nl2br=nl2br)
    except Exception:
        _log(traceback.format_exc())
        html = IDK

    view.update_popup(html)


def show_popup(
    view, content, md=True, css=None,
    flags=0, location=-1, max_width=320, max_height=240,
    on_navigate=None, on_hide=None, nl2br=True
):
    """Parse the color scheme if needed and show the styled pop-up."""

    disabled = _get_setting('mdpopups.disable', False)
    if disabled:
        _debug('Popups disabled', WARNING)
        return

    if not _can_show(view, location):
        return

    try:
        html = _create_html(view, content, md, css, css_type=POPUP, nl2br=nl2br)
    except Exception:
        _log(traceback.format_exc())
        html = IDK

    view.show_popup(
        html, flags=flags, location=location, max_width=max_width,
        max_height=max_height, on_navigate=on_navigate, on_hide=on_hide
    )


def is_popup_visible(view):
    """Check if popup is visible."""

    return view.is_popup_visible()


if PHANTOM_SUPPORT:
    def add_phantom(view, key, region, content, layout, md=True, css=None, on_navigate=None, nl2br=True):
        """Add a phantom and return phantom id."""

        disabled = _get_setting('mdpopups.disable', False)
        if disabled:
            _debug('Phantoms disabled', WARNING)
            return

        try:
            html = _create_html(view, content, md, css, css_type=PHANTOM, nl2br=nl2br)
        except Exception:
            _log(traceback.format_exc())
            html = IDK

        return view.add_phantom(key, region, html, layout, on_navigate)

    def erase_phantoms(view, key):
        """Erase phantoms."""

        view.erase_phantoms(key)

    def erase_phantom_by_id(view, pid):
        """Erase phantom by ID."""

        view.erase_phantom_by_id(pid)

    def query_phantom(view, pid):
        """Query phantom."""

        return view.query_phantom(pid)

    def query_phantoms(view, pids):
        """Query phantoms."""

        return view.query_phantoms(pids)

    class Phantom(sublime.Phantom):
        """A phantom object."""

        def __init__(self, region, content, layout, md=True, css=None, on_navigate=None, nl2br=True):
            """Initialize."""

            super().__init__(region, content, layout, on_navigate)
            self.md = md
            self.css = css
            self.nl2br = nl2br

        def __eq__(self, rhs):
            """Check if phantoms are equal."""

            # Note that self.id is not considered
            return (
                self.region == rhs.region and self.content == rhs.content and
                self.layout == rhs.layout and self.on_navigate == rhs.on_navigate and
                self.md == rhs.md and self.css == rhs.css and self.nl2br == rhs.nl2br
            )

    class PhantomSet(sublime.PhantomSet):
        """Object that allows easy updating of phantoms."""

        def __init__(self, view, key=""):
            """Initialize."""

            super().__init__(view, key)

        def __del__(self):
            """Delete phantoms."""

            for p in self.phantoms:
                erase_phantom_by_id(self.view, p.id)

        def update(self, new_phantoms):
            """Update the list of phantoms that exist in the text buffer with their current location."""

            regions = query_phantoms(self.view, [p.id for p in self.phantoms])
            for i in range(len(regions)):
                self.phantoms[i].region = regions[i]

            count = 0
            for p in new_phantoms:
                if not isinstance(p, Phantom):
                    # Convert sublime.Phantom to mdpopups.Phantom
                    p = Phantom(
                        p.region, p.content, p.layout,
                        md=False, css=None, on_navigate=p.on_navigate, nl2br=False
                    )
                    new_phantoms[count] = p
                try:
                    # Phantom already exists, copy the id from the current one
                    idx = self.phantoms.index(p)
                    p.id = self.phantoms[idx].id
                except ValueError:
                    p.id = add_phantom(
                        self.view,
                        self.key,
                        p.region,
                        p.content,
                        p.layout,
                        p.md,
                        p.css,
                        p.on_navigate,
                        p.nl2br
                    )
                count += 1

            for p in self.phantoms:
                # if the region is -1, then it's already been deleted, no need to call erase
                if p not in new_phantoms and p.region != sublime.Region(-1):
                    erase_phantom_by_id(self.view, p.id)

            self.phantoms = new_phantoms
