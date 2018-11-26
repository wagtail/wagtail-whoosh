import os
from setuptools import find_packages, setup

with open(os.path.join(os.path.dirname(__file__), 'README.md')) as readme:
    README = readme.read()

# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

setup(
    name='wagtail-whoosh',
    version='0.1',
    packages=find_packages(exclude=['tests']),
    include_package_data=True,
    license='BSD License',  # example license
    description='Whoosh backend for Wagtail CMS',
    long_description=README,
    url='https://github.com/tjwalch/wagtail-whoosh',
    author='MichaelYin',
    author_email='admin@michaelyin.info',
    classifiers=[
        'Environment :: Web Environment',
        'Framework :: Django',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',  # example license
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
    ],
    install_requires=[
        "wagtail==2.1",
        "Whoosh==2.7.4",
    ],
    test_suite='runtests.runtests'
)
