# -*- coding: utf-8 -*-
import codecs
import os
import re
import setuptools
from wikipedia.version import get_version


def local_file(file):
  ''' open the desired file in utf-8 '''
  return codecs.open(
    os.path.join(os.path.dirname(__file__), file), 'r', 'utf-8'
  )

install_reqs = [
  line.strip()
  for line in local_file('requirements.txt').readlines()
  if line.strip() != ''
]



setuptools.setup(
  name = "wikipedia",
  version = get_version(),
  author = "Tyler Barrus",
  author_email = "barrust@gmail.com",
  description = "Wikipedia API for Python (forked from https://github.com/goldsmith/Wikipedia)",
  license = "MIT",
  keywords = "python wikipedia API",
  url = "https://github.com/barrust/Wikipedia",
  install_requires = install_reqs,
  packages = ['wikipedia'],
  long_description = local_file('README.rst').read(),
  classifiers = [
    'Development Status :: 4 - Beta',
    'Topic :: Software Development :: Libraries',
    'License :: OSI Approved :: MIT License',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3'
  ],
  test_suite="tests"
)
