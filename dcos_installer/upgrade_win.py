"""
Generating upgrade script for Windows agent (dcos_node_upgrade.ps1)
"""

import uuid

import gen.build_deploy.util as util
import gen.calc
import gen.template
from dcos_installer.constants import SERVE_DIR
from pkgpanda.util import make_directory, write_string


node_upgrade_template = r"""
<#
.SYNOPSIS
  Name: dcos_node_upgrade.ps1
  The purpose of this script is to Upgrade DC/OS packages on Windows agent of a DC/OS cluster,
  another word to start Winpanda.py fetch & Winpanda.py upgrade

.EXAMPLE
#  .\dcos_node_upgrade.ps1
#>

# Metadata:
#   dcos image commit : {{ dcos_image_commit }}
#   generation date   : {{ generation_date }}

[CmdletBinding()]

# PARAMETERS
param (
    [Parameter(Mandatory=$false)] [string] $bootstrap_url = '{{ bootstrap_url }}',
    [Parameter(Mandatory=$false)] [string] $masters = '{{ master_list }}',
    [Parameter(Mandatory=$false)] [string] $install_dir = 'C:\d2iq\dcos',
    [Parameter(Mandatory=$false)] [string] $var_dir = 'C:\d2iq\dcos\var'
)

# GLOBAL
$global:basedir = "$($install_dir)"
$global:vardir  = "$($var_dir)"

$ErrorActionPreference = "Stop"

function Write-Log
{
    [CmdletBinding()]
    Param
    (
        [Parameter(Mandatory=$true,
                   ValueFromPipelineByPropertyName=$true)]
        [ValidateNotNullOrEmpty()]
        [Alias("LogContent")]
        [string]$Message,

        [Parameter(Mandatory=$false)]
        [Alias('LogPath')]
        [string]$Path="$($vardir)\log\dcos_node_upgrade.log",

        [Parameter(Mandatory=$false)]
        [ValidateSet("Error","Warn","Info","Debug")]
        [string]$Level="Info",

        [Parameter(Mandatory=$false)]
        [switch]$NoClobber
    )

    Begin
    {
        # Set VerbosePreference to Continue so that verbose messages are displayed.
        $VerbosePreference = 'Continue'
    }
    Process
    {

        # If the file already exists and NoClobber was specified, do not write to the log.
        if ((Test-Path $Path) -AND $NoClobber) {
            Write-Error "Log file $Path already exists, and you specified NoClobber. Either delete the file or specify a different name."
            Return
            }

        # If attempting to write to a log file in a folder/path that doesn't exist create the file including the path.
        elseif (!(Test-Path $Path)) {
            Write-Verbose "Creating $Path."
            $NewLogFile = New-Item $Path -Force -ItemType File
            }

        else {
            # Nothing to see here yet.
            }

        # Format Date for our Log File
        $FormattedDate = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

        # Write message to error, warning, or verbose pipeline and specify $LevelText
        switch ($Level) {
            'Error' {
                Write-Error $Message
                $LevelText = 'ERROR:'
                }
            'Warn' {
                Write-Warning $Message
                $LevelText = 'WARNING:'
                }
            'Info' {
                Write-Host $Message
                $LevelText = 'INFO:'
                }
            'Debug' {
                Write-Verbose $Message
                $LevelText = 'DEBUG:'
                }
            }

        # Write log entry to $Path
        "$FormattedDate $LevelText $Message" | Tee-Object -FilePath $Path -Append
    }
    End
    {
    }
}

function Test-CalledFromPrompt {
    (Get-PSCallStack)[-2].Command -eq "prompt"
}

function Invoke-NativeApplication {
    param
    (
        [ScriptBlock] $ScriptBlock,
        [int[]] $AllowedExitCodes = @(0),
        [switch] $IgnoreExitCode
    )
    [string] $stringScriptBlock = $ScriptBlock.ToString();
    $backupErrorActionPreference = $ErrorActionPreference;
    $ErrorActionPreference = "Continue";
    try
    {
        if (Test-CalledFromPrompt)
        {
            $lines = & $ScriptBlock 2>&1 | Tee-Object -FilePath "$($vardir)\log\dcos_node_upgrade.log" -Append
        }
        else
        {
            $lines = & $ScriptBlock 2>&1 | Tee-Object -FilePath "$($vardir)\log\dcos_node_upgrade.log" -Append
        }
        $lines | ForEach-Object -Process `
            {
                $isError = $_ -is [System.Management.Automation.ErrorRecord]
                "$_" | Add-Member -Name IsError -MemberType NoteProperty -Value $isError -PassThru
            }
        if ((-not $IgnoreExitCode) -and ($AllowedExitCodes -notcontains $LASTEXITCODE))
        {
            throw "$(Get-Date -Format "yyyy-MM-dd HH:mm:ss") ERROR: Failed to execute `'$stringScriptBlock`' : returned $LASTEXITCODE. Check logs at $($vardir)\log\ or traceback for more details!" 2>&1 | Tee-Object -FilePath "$($vardir)\log\dcos_node_upgrade.log" -Append
        }
    }
    finally
    {
        $ErrorActionPreference = $backupErrorActionPreference
    }
}

function SetupDirectories() {
    # available directories
    $dirs = @(
        "C:\d2iq",
        "C:\d2iq\dcos",
        "C:\d2iq\dcos\etc",
        "$($basedir)",
        "$($basedir)\bootstrap",
        "$($basedir)\bootstrap\prerequisites",
		"$($basedir)\bin",
        "$($basedir)\etc",
        "$($vardir)",
        "$($vardir)\log"
    )
    # setup
    Write-Log -Level "Info" -LogContent "Creating a directories structure:"
    foreach ($dir in $dirs) {
        if (-not (test-path "$dir") ) {
            Write-Log -Level "Debug" -LogContent "$($dir) doesn't exist, creating it"
            New-Item -Path $dir -ItemType directory | Out-Null
        } else {
            Write-Log -Level "Debug" -LogContent "$($dir) exists, no need to create it"
        }
    }
}

function CreateWriteFile([String] $dir, [String] $file, [String] $content) {
    Write-Log -Level "Debug" -LogContent "vars: $dir, $file, $content"
    if (-not (test-path "$($dir)\$($file)") ) {
        Write-Log -Level "Debug" -LogContent "Creating $($file) at $($dir)"
    }
    else {
        Write-Log -Level "Warn" -LogContent "$($dir)\$($file) already exists. Re-writing"
        Remove-Item "$($dir)\$($file)"
    }
    New-Item -Path "$($dir)\$($file)" -ItemType File
    Write-Log -Level "Info" -LogContent "Writing content to $($file)"
    Add-Content "$($dir)\$($file)" "$($content)"
    Get-Content "$($dir)\$($file)"
}


function main($url, $masters) {
    SetupDirectories

    # Fill up gen_out arguments to cluster.conf
    Write-Log -Level "Debug" -LogContent "MASTERS: $($masters)"
    [System.Array]$masterarray = $masters.replace('"', '').replace('[', '').replace(']', '').replace(' ', '').split(',')
    $masternodecontent = ""
    for ($i=0; $i -lt $masterarray.length; $i++) {
        $masternodecontent += "[master-node-$($i+1)]`nPrivateIPAddr=$($masterarray[$i])`nZookeeperListenerPort=2181`n"
    }
    $local_ip = Invoke-NativeApplication {. "$($basedir)\bin\detect_ip.ps1"}
    Write-Log -Level "Debug" -LogContent "Local IP: $($local_ip)"
    $content = "$($masternodecontent)`n[distribution-storage]`nRootUrl=$($url)`nPkgRepoPath=windows/packages`nPkgListPath=windows/package_lists/latest.package_list.json`nDcosClusterPkgInfoPath=cluster-package-info.json`n`n[local]`nPrivateIPAddr=$($local_ip)"
    CreateWriteFile "$($basedir)\etc" "cluster.conf" $content

    Write-Log -Level "Info" -LogContent "Running Winpanda.py upgrade ..."
    Invoke-NativeApplication {python.exe "$($basedir)\winpanda\bin\winpanda.py" --inst-root-dir="$($basedir)" upgrade}
    Write-Log -Level "Info" -LogContent "dcos_node_upgrade.ps1 successfully finished."
}

main $bootstrap_url $masters

"""


def generate_node_upgrade_win_script(gen_out, installed_cluster_version, serve_dir=SERVE_DIR):

    # installed_cluster_version: Current installed version on the cluster
    # installer_version: Version we are upgrading to

    bootstrap_url = gen_out.arguments['bootstrap_url']
    master_list = gen_out.arguments['master_list']
    installer_version = gen.calc.entry['must']['dcos_version']

    powershell_script = gen.template.parse_str(node_upgrade_template).render({
        'dcos_image_commit': util.dcos_image_commit,
        'generation_date': util.template_generation_date,
        'bootstrap_url': bootstrap_url,
        'master_list': master_list,
        'installed_cluster_version': installed_cluster_version,
        'installer_version': installer_version})

    upgrade_script_path = '/windows/upgrade/' + uuid.uuid4().hex
    make_directory(serve_dir + upgrade_script_path)
    write_string(serve_dir + upgrade_script_path + '/dcos_node_upgrade.ps1', powershell_script)
    print("Windows agent upgrade script URL: " + bootstrap_url + upgrade_script_path + '/dcos_node_upgrade.ps1')
    return 0
