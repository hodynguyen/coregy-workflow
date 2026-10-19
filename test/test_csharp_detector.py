"""Tests for C#/.NET detector."""
import os
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "plugins",
    "coregy-workflow",
    "skills",
    "project-profile",
    "scripts",
)
sys.path.insert(0, os.path.abspath(SCRIPT_DIR))

from detectors.profile import build_profile


class TestCSharpProject(unittest.TestCase):
    def test_aspnet_core(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "MyApp.csproj"), "w") as f:
                f.write('<Project Sdk="Microsoft.NET.Sdk.Web">\n<PackageReference Include="Microsoft.AspNetCore" />\n<PackageReference Include="Microsoft.EntityFrameworkCore" />\n<PackageReference Include="xunit" />\n</Project>\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["project"]["type"], "backend")
            self.assertEqual(profile["backend"]["language"], "csharp")
            self.assertEqual(profile["backend"]["framework"], "aspnet-core")
            self.assertEqual(profile["backend"]["orm"], "entity-framework")
            self.assertEqual(profile["backend"]["testing"], "xunit")

    def test_blazor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "App.csproj"), "w") as f:
                f.write('<Project Sdk="Microsoft.NET.Sdk.Blazor">\n<PackageReference Include="nunit" />\n</Project>\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["framework"], "blazor")
            self.assertEqual(profile["backend"]["testing"], "nunit")

    def test_dotnet_sln_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "MyApp.sln"), "w") as f:
                f.write("Microsoft Visual Studio Solution File\n")
            with open(os.path.join(tmpdir, "MyApp.csproj"), "w") as f:
                f.write('<Project Sdk="Microsoft.NET.Sdk">\n</Project>\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["language"], "csharp")
            self.assertEqual(profile["backend"]["framework"], "dotnet")

    def test_dapper_orm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Api.csproj"), "w") as f:
                f.write('<Project>\n<PackageReference Include="Microsoft.AspNetCore" />\n<PackageReference Include="Dapper" />\n<PackageReference Include="MSTest" />\n</Project>\n')
            profile = build_profile(tmpdir)
            self.assertEqual(profile["backend"]["orm"], "dapper")
            self.assertEqual(profile["backend"]["testing"], "mstest")


if __name__ == "__main__":
    unittest.main()
