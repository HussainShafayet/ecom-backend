import nh3

# Rich text written by staff (product descriptions, CMS captions) is rendered by the frontend with
# dangerouslySetInnerHTML, so everything that is not on this list is stripped when it is written.
ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "em", "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "pre",
    "s", "span", "strong", "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto", "tel"}  # no javascript: / data:


def sanitize_html(value):
    """Return `value` with scripts, event handlers, styles and unknown tags removed. Empty in, empty out."""
    if not value:
        return ""
    return nh3.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer nofollow",
    )
