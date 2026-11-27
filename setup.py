from setuptools import find_namespace_packages, setup

# The package's code sits directly in src/: its subpackages are found there and get the package name in front.
PACKAGE = "yorha"

setup(
    package_dir={PACKAGE: "src"},
    packages=[PACKAGE] + [f"{PACKAGE}.{name}" for name in find_namespace_packages("src", exclude=["*__pycache__*"])],
)
