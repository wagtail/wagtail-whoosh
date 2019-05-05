PHONY: test unittests flaketest checkmanifest checksetup clean build release

test: unittests flaketest checkmanifest checksetup

unittests:
	# Run unit tests
	python setup.py test

flaketest:
	flake8

pylint:
	# Check syntax and style
	flake8
	isort --recursive wagtail_whoosh

checkmanifest:
	# Check if all files are included in the sdist
	check-manifest

checksetup:
	# Check longdescription and metadata
	python setup.py check -msr

clean:
	# Remove build and dist dirs
	rm -rf build dist

build: test clean
	# Test, clean and build dist
	python setup.py build sdist bdist_wheel

release: build
	# Build and upload to PyPI
	twine upload dist/*
