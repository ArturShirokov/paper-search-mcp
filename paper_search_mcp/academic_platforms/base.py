"""Base class for all academic paper source searchers."""
from abc import ABC, abstractmethod
import xml.etree.ElementTree as ET
from typing import Any, List

import requests

from ..paper import Paper


def retry_hint(response: requests.Response) -> str:
    """' (Retry-After: N)' when the reply says when to come back, else ''."""
    value = response.headers.get("Retry-After")
    return f" (Retry-After: {value})" if value else ""


def check_response(response: requests.Response, source: str) -> None:
    """Raise requests.HTTPError unless the reply is 2xx.

    The message leaves out the URL, which can carry API keys, and keeps the
    Retry-After value so a rate limit says when to come back.
    """
    if 200 <= response.status_code < 300:
        return
    message = f"{source} returned HTTP {response.status_code}{retry_hint(response)}"
    raise requests.HTTPError(message, response=response)


def json_body(response: requests.Response, source: str) -> Any:
    """Parse a JSON reply, or raise ValueError naming what came back instead."""
    try:
        return response.json()
    except ValueError:
        content_type = response.headers.get("Content-Type") or "no content type"
        raise ValueError(f"{source} returned a non-JSON reply ({content_type})") from None


def xml_root(response: requests.Response, source: str, expected_tag: str | None) -> ET.Element:
    """Check status, parse XML and require the root element, or raise.

    The root check matters: an HTML error page can parse as XML and would
    otherwise read as zero hits. Pass None to check the root yourself.
    """
    check_response(response, source)
    content_type = response.headers.get("Content-Type") or "no content type"
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError:
        raise ValueError(f"{source} returned a non-XML reply ({content_type})") from None
    if expected_tag is not None and root.tag != expected_tag:
        raise ValueError(
            f"{source} returned an unexpected reply (<{root.tag}>, {content_type})"
        )
    return root


class PaperSource(ABC):
    """Abstract base class for academic paper sources."""

    @abstractmethod
    def search(self, query: str, **kwargs) -> List[Paper]:
        """Search papers matching the query.

        Args:
            query: Search query string.
            **kwargs: Source-specific parameters (e.g., max_results, year).

        Returns:
            List of Paper objects.
        """

    def download_pdf(self, paper_id: str, save_path: str) -> str:
        """Download the PDF for a given paper.

        Args:
            paper_id: Platform-specific paper identifier.
            save_path: Directory to save the downloaded PDF.

        Returns:
            Path to the saved PDF file.

        Raises:
            NotImplementedError: If the source does not support PDF downloads.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support PDF downloads."
        )

    def read_paper(self, paper_id: str, save_path: str = "./downloads") -> str:
        """Download and extract text from a paper PDF.

        Args:
            paper_id: Platform-specific paper identifier.
            save_path: Directory where the PDF is/will be saved.

        Returns:
            Extracted text content of the paper.

        Raises:
            NotImplementedError: If the source does not support paper reading.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support reading paper content."
        )
