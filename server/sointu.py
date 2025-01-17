from typing import Self
from server.dependency import (
    Dependencies,
    Dependency,
)
from subprocess import (
    run,
    CompletedProcess,
)
from tempfile import TemporaryDirectory
from pathlib import Path
from importlib.resources import files
from server import templates
from winreg import (
    ConnectRegistry,
    OpenKey,
    HKEY_LOCAL_MACHINE,
    HKEYType,
    QueryValueEx,
)
from jinja2 import (
    Environment,
    FileSystemLoader,
)
from unit import Instrument
from yaml import safe_load, dump

class SointuCompileError(Exception):
    pass

class AssemblerError(Exception):
    pass

class LinkerError(Exception):
    pass

class WavWriterError(Exception):
    pass

# Wow, I can not begin to comprehend how an unsuitable Moloch like
# the Windows registry is considered useful by some individuals.
# I do not want to write or maintain any of the bloated code below.
registry: HKEYType = ConnectRegistry(None, HKEY_LOCAL_MACHINE)
windowsSdkKey: HKEYType = OpenKey(registry, r'SOFTWARE\WOW6432Node\Microsoft\Microsoft SDKs\Windows\v10.0')
windowsSdkProductVersion, _ = QueryValueEx(windowsSdkKey, r'ProductVersion')
windowsSdkInstallFolder, _ = QueryValueEx(windowsSdkKey, r'InstallationFolder')
windowsSdkKey.Close()
registry.Close()
WindowsSdkLibPath: Path = Path(windowsSdkInstallFolder) / 'Lib' / '{}.0'.format(windowsSdkProductVersion) / 'um' / 'x86'

class Sointu:
    @staticmethod
    def yamlToWave(yaml: str) -> bytes:
        outputDirectory: TemporaryDirectory = TemporaryDirectory()

        # Write yaml file.
        yaml_file: Path = Path(outputDirectory.name) / 'music.yml'
        yaml_file.write_text(yaml)

        # Compile yaml file using sointu.
        track_asm_file: Path = Path(outputDirectory.name) / 'music.asm'
        result: CompletedProcess = run([
            Dependencies[Dependency.Sointu],
            '-arch', '386',
            '-e', 'asm,inc',
            '-o', track_asm_file,
            yaml_file,
        ])
        if result.returncode != 0:
            raise SointuCompileError('Could not compile track: {}.'.format(yaml_file))

        # Assemble the wav writer.
        wav_asm_file: Path = Path(files(templates) / 'wav.asm')
        wav_obj_file: Path = Path(outputDirectory.name) / 'wav.obj'
        wav_file: Path = Path(outputDirectory.name) / 'music.wav'
        result: CompletedProcess = run([
            Dependencies[Dependency.Nasm],
            '-f', 'win32',
            '-I', Path(outputDirectory.name),
            wav_asm_file,
            '-DTRACK_INCLUDE="{}"'.format(Path(outputDirectory.name) / 'music.inc'),
            '-DFILENAME="{}"'.format(wav_file),
            '-o', wav_obj_file,
        ])
        if result.returncode != 0:
            raise AssemblerError('Could not assemble track: {}.'.format(wav_asm_file))

        # Assemble track.
        track_obj_file: Path = Path(outputDirectory.name) / 'music.obj'
        result: CompletedProcess = run([
            Dependencies[Dependency.Nasm],
            '-f', 'win32',
            '-I', Path(outputDirectory.name),
            track_asm_file,
            '-o', track_obj_file,
        ])

        # Link wav writer.
        # Note: When using the list based api, quotes in arguments
        # are not escaped properly. How annoying can it get?!
        wav_exe = Path(outputDirectory.name) / 'wav.exe'
        result: CompletedProcess = run(' '.join(map(str, [
            Dependencies[Dependency.Crinkler],
            '/LIBPATH:"{}"'.format(Path(outputDirectory.name)),
            '/LIBPATH:"{}"'.format(WindowsSdkLibPath),
            wav_obj_file,
            track_obj_file,
            '/OUT:{}'.format(wav_exe),
            'Winmm.lib',
            'Kernel32.lib',
            'User32.lib',
        ])), shell=True)
        if result.returncode != 0:
            raise LinkerError('Unable to link {}.'.format(wav_exe))

        # Write wave file
        result: CompletedProcess = run([
            wav_exe,
        ])
        if result.returncode != 0:
            raise WavWriterError('Unable to write wav {}.'.format(wav_file))

        return wav_file.read_bytes()

if __name__ == '__main__':
    instrument: Instrument = Instrument.parse(Path(files(templates) / 'instrument.yml').read_text())
    
    sequenceObject = safe_load(Path(files(templates) / 'sequence.yml').read_text())
    sequenceObject['patch'] = [instrument.serialize()] + sequenceObject['patch']
    print(dump(sequenceObject, indent=2))

    Path(files(templates) / 'test.wav').write_bytes(Sointu.yamlToWave(dump(sequenceObject)))

    # print(instrument.randomize())
    # print(Sointu.yamlToWave(Path(files(templates) / '21.yml').read_text()))
