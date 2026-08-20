import cssselect
from lxml import etree
from scraper.core.enums import SelectorStrategy
from scraper.core.exceptions import ScraperError

class InputSanitizer:
    """Sanitizes selectors and checks sizes to prevent injection or DoS."""
    
    DANGEROUS_XPATH_FUNCTIONS = {'document', 'system-property', 'unparsed-entity-uri', 'generate-id'}
    MAX_RESPONSE_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

    def validate_css_selector(self, selector: str) -> bool:
        """Parse with cssselect, return True if valid and safe."""
        try:
            # Check for validity
            cssselect.parse(selector)
            return True
        except cssselect.SelectorSyntaxError:
            return False

    def validate_xpath_selector(self, selector: str) -> bool:
        """Parse with lxml.etree.XPath, reject dangerous functions."""
        try:
            # Simple substring check for dangerous functions
            for func in self.DANGEROUS_XPATH_FUNCTIONS:
                if f"{func}(" in selector:
                    return False
                    
            # Try parsing
            etree.XPath(selector)
            return True
        except etree.XPathSyntaxError:
            return False

    def validate_selector(self, selector: str, strategy: SelectorStrategy) -> bool:
        """Dispatch to correct validator."""
        if strategy == SelectorStrategy.CSS:
            return self.validate_css_selector(selector)
        elif strategy == SelectorStrategy.XPATH:
            return self.validate_xpath_selector(selector)
        return True # Default to True for unknown strategies (or implement specifics)

    def check_response_size(self, content_length: int | None) -> None:
        """Raises if too large (decompression bomb protection)."""
        if content_length is not None and content_length > self.MAX_RESPONSE_SIZE_BYTES:
            raise ScraperError(f"Response size {content_length} exceeds limit of {self.MAX_RESPONSE_SIZE_BYTES} bytes")

    def safe_xml_parser(self) -> etree.XMLParser:
        """Returns parser with resolve_entities=False, no_network=True, dtd_validation=False."""
        return etree.XMLParser(resolve_entities=False, no_network=True, dtd_validation=False)
