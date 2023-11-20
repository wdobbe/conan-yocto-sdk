from conan import ConanFile
from conan import tools
import os, glob, re, shutil, stat
from pathlib import Path


class DynniqSdkCortexA9hf(ConanFile):
    name = "dynniq_yocto_sdk_cortexa9hf"
    build_policy = "missing"
    upload_policy = "skip"
    settings = { "os", "arch" }
    package_type = "unknown"
    sdk_file = None
    exports_sources = "dynniq-yoctosdk-x86_64-*-toolchain-*.sh"

    def configure(self):
        self.targetarch = "cortexa9hf-neon"
        self.sdk_file = 'dynniq-yoctosdk-x86_64-' + self.targetarch + '-toolchain-' + self.version + '.sh'
        
    def validate(self):
        if self.settings.os != 'Linux':
            raise ConanInvalidConfiguration("This SDK can only be installed on Linux")
        if self.settings.arch != 'x86_64':
            raise ConanInvalidConfiguration("This SDK can only be installed on x86_64 architecture")

    def package(self):
        sdkpath = os.path.join(self.source_folder, self.sdk_file)
        print("self.source_folder: " + self.source_folder)
        print("sdkpath: " + sdkpath)
        os.chmod(sdkpath, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IXUSR | stat.S_IXGRP)
        command = sdkpath + " -y -d %s" % self.package_folder
        self.run(command)
        sudo_exe = os.path.join(self.package_folder, 'sysroots', self.targetarch + '-poky-linux-gnueabi/usr/bin/sudo')
        os.chmod(sudo_exe, stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        #When using Conan, cmake should no longer search only in the SDK sysroot directories but also in the conan package
        #directories. Patch the SDK cmake toolchain file for this.
        toolchainFile = os.path.join(self.package_folder, "sysroots", "x86_64-pokysdk-linux", "usr", "share", "cmake", "OEToolchainConfig.cmake")
        sedCmd = "sed -i -e '/CMAKE_FIND_ROOT_PATH_MODE_LIBRARY/d' -e '/CMAKE_FIND_ROOT_PATH_MODE_INCLUDE/d' " \
                 "-e '/CMAKE_FIND_ROOT_PATH_MODE_PACKAGE/d' %s" % toolchainFile
        self.run(sedCmd, cwd=os.path.join(self.package_folder, "sysroots", "x86_64-pokysdk-linux", "usr", "share", "cmake"), env="msys_mingw=False")
        #We also want to use cmake from the Conan cmake package i.s.o. the cmake in the SDK, so delete cmake from the SDK
        os.remove( os.path.join( self.package_folder, "sysroots", "x86_64-pokysdk-linux", "usr", "bin", "cmake") )
        cmake_share_dirs = glob.glob( os.path.join(self.package_folder, "sysroots", "x86_64-pokysdk-linux", "usr", "share", "cmake-*") )
        for nextDir in cmake_share_dirs:
            shutil.rmtree(nextDir)

    def export_sdk_setup_variables(self, envSetupFile):
        # Read all variables into a dictionary first so that we can resolve
              # references later.
              env = {}
              with open(envSetupFile) as f:
                  for line in f:
                      match = re.search(r'export ([^=]+)=(.*)', line)
                      if match:
                          key = match.group(1)
                          # Strip possible quotes around the value
                          value = match.group(2).strip("\"")
                          env[key] = value
  
              # CROSS_COMPILE setting from Yocto env interferes with OpenSSL/crypto build
              # which uses $CROSS_COMPILE$CC as compiler command but Yocto already adds the
              # target prefix to $CC. We just remove it from the environment for now. This
              # should not affect any other builds.
              if "CROSS_COMPILE" in env:
                  del env["CROSS_COMPILE"]

              for key, value in env.items():
                  # Remove references to self (e.g. in PATH=...:$PATH)
                  value = re.sub("\\$%s" % key, "", value)
                  # Find all other references and resolve them
                  buildEnvVars = self.buildenv_info.vars(self)
                  refs = re.findall(r'\$[a-zA-Z0-9_]+', value)
                  for ref in refs:
                      if ref[1:] in env:
                          value = re.sub("\\%s" % ref, env[ref[1:]], value)
                      else:
                          value = re.sub("\\%s" % ref, buildEnvVars.get(ref[1:]), value)
                  if key.lower() == "path":
                      # The content of the PATH variable must be set as a list to make
                      # Conan append to the existing PATH. Otherwise it will overwrite
                      # the environment variable.
                      currPath = [ os.environ['PATH'] if 'PATH' in os.environ else '' ]
                      newPath = currPath + [x for x in value.split(":") if x]
                      #setattr(self.buildenv_info, key, newPath)
                      self.buildenv_info.define(key, newPath)
                  else:
                      # All other variables can be handled in the standard way.
                      #setattr(self.buildenv_info, key, value)
                      self.buildenv_info.define(key, value)


    def package_info(self):
        # We parse the environment-setup script generated by Yocto to obtain all
        # of the environment variables needed for building and append them to
        # the env_info attribute of the toolchain package. That will make Conan
        # apply the environment to all package builds which reference the
        # toolchain package in their build_requires.
        envSetupFileList = glob.glob(os.path.join(self.package_folder, "environment-setup*"))
        envSetupFile = envSetupFileList[0] if envSetupFileList else None
        buildEnvVars = self.buildenv_info.vars(self, 'build')
        if envSetupFile:
            self.export_sdk_setup_variables(envSetupFile)

        target_sysroot = buildEnvVars.get('OECORE_TARGET_SYSROOT')
        if target_sysroot and Path(os.path.join(target_sysroot, 'environment-setup.d')).exists:
            envSetupFileList = glob.glob(os.path.join(target_sysroot, 'environment-setup.d', '*.sh'))
            for envSetupFile in envSetupFileList:
                self.export_sdk_setup_variables(envSetupFile)
  
        native_sysroot = buildEnvVars.get('OECORE_NATIVE_SYSROOT')
        if native_sysroot and Path(os.path.join(native_sysroot, 'environment-setup.d')).exists:
            envSetupFileList = glob.glob(os.path.join(native_sysroot, 'environment-setup.d', '*.sh'))
            for envSetupFile in envSetupFileList:
                self.export_sdk_setup_variables(envSetupFile)

        # Unset command_not_found_handle to fix problems on Ubuntu due to
        # toolchains overriding PYTHONHOME (typing an unknown command in a shell
        # on Ubuntu will run a Python script which will no longer work when a
        # toolchain redefines PYTHONHOME).
        self.buildenv_info.command_not_found_handle = None
        toolchain = os.path.join(self.package_folder, "sysroots", "x86_64-pokysdk-linux", "usr", "share", "cmake", "OEToolchainConfig.cmake")
        #setattr(self.buildenv_info, "CONAN_CMAKE_TOOLCHAIN_FILE", toolchain)
        self.buildenv_info.define("CONAN_CMAKE_TOOLCHAIN_FILE", toolchain)
        
        target_sysroot = os.path.join(self.package_folder, "sysroots", "cortexa9hf-neon-poky-linux-gnueabi")
        self.conf_info.define("tools.build:sysroot", target_sysroot)
        compiler_executables = {
            "c": os.path.join(self.package_folder, "sysroots", "x86_64-pokysdk-linux", "usr", "bin", "arm-poky-linux-gnueabi", "arm-poky-linux-gnueabi-gcc"),
            "cpp": os.path.join(self.package_folder, "sysroots", "x86_64-pokysdk-linux", "usr", "bin", "arm-poky-linux-gnueabi", "arm-poky-linux-gnueabi-g++")
        }
        self.conf_info.update("tools.build:compiler_executables", compiler_executables)
        #currCFlags = self.conf_info.get("tools.build:flags".get_safe("CFLAGS")
        #currCFlagsEnv = os.environ.get("CFLAGS", "")
        #currCxxFlags = self.conf_info["tools.build:flags"].get_safe("CXXFLAGS")
        #currCxxFlagsEnv = os.environ.get("CXXFLAGS", "")
        #currLdFlags = self.conf_info["tools.build:flags"].get_safe("LDFLAGS")
        newCFlags = "-marm -mfpu=neon -mfloat-abi=hard -mcpu=cortex-a9 -fstack-protector-strong  -D_FORTIFY_SOURCE=2 -Wformat -Wformat-security -Werror=format-security --sysroot=" + os.path.join(self.package_folder, "sysroots", "cortexa9hf-neon-poky-linux-gnueabi")
        newCxxFlags = "-marm -mfpu=neon -mfloat-abi=hard -mcpu=cortex-a9 -fstack-protector-strong  -D_FORTIFY_SOURCE=2 -Wformat -Wformat-security -Werror=format-security --sysroot=" + os.path.join(self.package_folder, "sysroots", "cortexa9hf-neon-poky-linux-gnueabi")
        self.buildenv_info.define("CFLAGS", newCFlags)
        self.buildenv_info.define("CXXFLAGS", newCxxFlags)

