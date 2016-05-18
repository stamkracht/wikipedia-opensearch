# -*- coding: utf-8 -*-
import unittest

from collections import defaultdict

from wikipedia import wikipedia
from request_mock_data import mock_data


# mock out _wiki_request
class _wiki_request(object):
    ''' _wiki_request override '''
    calls = defaultdict(int)

    @classmethod
    def __call__(cls, params):
        cls.calls[params.__str__()] += 1
        return mock_data["_wiki_request calls"][tuple(sorted(params.items()))]

wikipedia._wiki_request = _wiki_request()


class TestOpensearch(unittest.TestCase):
    """Test the functionality of wikipedia.opensearch."""

    def test_suggestion(self):
        """Test search suggestion."""
        osr = wikipedia.opensearch('Floortje Dressing')[0]
        self.assertEqual(osr.title, mock_data['data']['floortje']['title'])
        self.assertEqual(osr.summary, mock_data['data']['floortje']['summary'])
        self.assertEqual(osr.url, mock_data['data']['floortje']['url'])

    def test_return_redirect(self):
        """Test returning redirect title and url."""
        wikipedia.set_lang('nl')

        osr = wikipedia.opensearch('gengis kan', redirects='return')[0]
        self.assertEqual(osr.title, mock_data['data']['nl_gengis']['title'])
        self.assertEqual(osr.summary, mock_data['data']['nl_gengis']['summary'])
        self.assertEqual(osr.url, mock_data['data']['nl_gengis']['url'])

        wikipedia.set_lang('en')

    def test_suggestion_none(self):
        """Test getting a suggestion when there is no suggestion."""
        results = wikipedia.opensearch("qmxjsudek")
        self.assertEqual(results, [])
