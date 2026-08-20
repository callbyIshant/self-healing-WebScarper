import re
import structlog
from lxml import html
from lxml.etree import ParserError

logger = structlog.get_logger(__name__)

class AXTreeSanitizer:
    """
    Pre-LLM content sanitization pipeline to mitigate prompt injection.
    """
    
    INJECTION_PATTERNS = [
        r"(?i)ignore\s+previous",
        r"(?i)system\s+override",
        r"(?i)you\s+are\s+now",
        r"(?i)dan\s+mode",
        r"(?i)system:",
        r"(?i)assistant:",
    ]
    
    def __init__(self) -> None:
        self.injection_regex = [re.compile(p) for p in self.INJECTION_PATTERNS]

    def strip_hidden_elements(self, content: str) -> str:
        try:
            parser = html.HTMLParser(resolve_entities=False, no_network=True)
            tree = html.fromstring(content, parser=parser)
        except ParserError:
            return content
        
        for element in tree.xpath('//*[@style] | //*[@hidden] | //*[@type="hidden"]'):
            if element.get('hidden') is not None or str(element.get('type')).lower() == 'hidden':
                element.drop_tree()
                continue
                
            style = element.get('style', '').lower().replace(' ', '')
            if 'display:none' in style or 'visibility:hidden' in style or 'opacity:0' in style:
                element.drop_tree()
                
        return html.tostring(tree, encoding='unicode', method='html')

    def strip_executable_nodes(self, content: str) -> str:
        try:
            parser = html.HTMLParser(resolve_entities=False, no_network=True)
            tree = html.fromstring(content, parser=parser)
        except ParserError:
            return content
            
        for tag in ['script', 'style', 'iframe', 'noscript', 'object', 'embed', 'svg']:
            for element in tree.xpath(f'//{tag}'):
                element.drop_tree()
                
        return html.tostring(tree, encoding='unicode', method='html')

    def strip_event_handlers(self, content: str) -> str:
        # Removes on* attributes
        return re.sub(r'(?i)\s+on[a-z]+\s*=\s*(["\']).*?\1', '', content)

    def strip_data_attributes(self, content: str) -> str:
        # Removes data-* attributes except data-testid
        # A simpler regex approach for attributes
        return re.sub(r'(?i)\s+data-(?!testid=)[a-z0-9\-]+\s*=\s*(["\']).*?\1', '', content)

    def truncate_text_nodes(self, text: str, max_length: int = 500) -> str:
        if len(text) > max_length:
            return text[:max_length] + "..."
        return text

    def strip_unicode_obfuscation(self, text: str) -> str:
        # Remove zero-width chars, bidi overrides, etc.
        chars_to_remove = ['\u200B', '\uFEFF', '\u202E', '\u202D', '\u202C', '\u202A', '\u202B']
        for c in chars_to_remove:
            text = text.replace(c, '')
        return text

    def escape_xml_delimiters(self, content: str) -> str:
        # Escape any existing </untrusted_scraped_content> to prevent breakouts
        return content.replace("</untrusted_scraped_content>", "&lt;/untrusted_scraped_content&gt;")

    def wrap_untrusted(self, content: str) -> str:
        return f"<untrusted_scraped_content>\n{content}\n</untrusted_scraped_content>"

    def scan_for_injection_patterns(self, content: str) -> list[str]:
        matches = []
        for regex in self.injection_regex:
            if regex.search(content):
                matches.append(regex.pattern)
        return matches

    def sanitize(self, raw_content: str) -> tuple[str, list[str]]:
        detected_patterns = self.scan_for_injection_patterns(raw_content)
        
        # We might want to use lxml for html parsing if it's html, 
        # but since AXTree can be text or HTML, we apply text-based and HTML-based methods.
        content = self.strip_unicode_obfuscation(raw_content)
        content = self.strip_executable_nodes(content)
        content = self.strip_hidden_elements(content)
        content = self.strip_event_handlers(content)
        content = self.strip_data_attributes(content)
        content = self.truncate_text_nodes(content)
        content = self.escape_xml_delimiters(content)
        content = self.wrap_untrusted(content)
        
        return content, detected_patterns
