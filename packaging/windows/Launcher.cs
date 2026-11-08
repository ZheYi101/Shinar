using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

[assembly: AssemblyTitle("Shinar")]
[assembly: AssemblyDescription("Shinar desktop launcher")]
[assembly: AssemblyCompany("Shinar")]
[assembly: AssemblyProduct("Shinar")]
[assembly: AssemblyVersion("@@VERSION@@")]
[assembly: AssemblyFileVersion("@@VERSION@@")]

internal static class Launcher
{
    private static bool quiet;
    // Windows CommandLineToArgvW quoting, including trailing backslashes.
    private static string QuoteArgument(string value)
    {
        var output = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"') { output.Append('\\', slashes * 2 + 1); }
            else { output.Append('\\', slashes); }
            output.Append(c);
            slashes = 0;
        }
        output.Append('\\', slashes * 2);
        return output.Append('"').ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        quiet = Array.IndexOf(args, "--smoke") >= 0;
        try
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "runtime", "pythonw.exe");
            if (!File.Exists(python))
                throw new FileNotFoundException();
            var arguments = new StringBuilder("-I -B -m shinar.desktop.packaged");
            foreach (string arg in args)
                arguments.Append(' ').Append(QuoteArgument(arg));
            var start = new ProcessStartInfo(python, arguments.ToString());
            start.WorkingDirectory = root;
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            foreach (string key in new[] {
                "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "QT_PLUGIN_PATH",
                "QT_QPA_PLATFORM_PLUGIN_PATH", "QML_IMPORT_PATH", "QML2_IMPORT_PATH"
            }) start.EnvironmentVariables.Remove(key);
            using (var process = Process.Start(start))
            {
                process.WaitForExit();
                if (process.ExitCode != 0)
                    ShowError("启动失败，错误码：" + process.ExitCode);
                return process.ExitCode;
            }
        }
        catch
        {
            ShowError("无法启动应用。请重新解压或安装 Shinar。");
            return 1;
        }
    }

    private static void ShowError(string detail)
    {
        if (quiet) return;
        MessageBox.Show(detail, "Shinar", MessageBoxButtons.OK, MessageBoxIcon.Error);
    }
}
