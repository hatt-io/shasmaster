using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32.SafeHandles;

// Windows supplies .NET Framework; the reader and Python runtime are bundled.
internal static class WindowsApp
{
    static Process backend;
    static bool started;
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
        public uint ActiveProcesses;
        public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct IoCounters { public ulong Reads, Writes, Other, ReadBytes, WriteBytes, OtherBytes; }
    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits {
        public BasicLimits Basic;
        public IoCounters Io;
        public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern SafeFileHandle CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetInformationJobObject(SafeFileHandle job, int kind, ref ExtendedLimits limits, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool AssignProcessToJobObject(SafeFileHandle job, IntPtr process);
    static readonly int Port = int.Parse(Environment.GetEnvironmentVariable("SHAS_PORT") ?? "9473");
    static readonly string Origin = "http://127.0.0.1:" + Port;
    static bool headless;
    static void OpenReader() { Process.Start(new ProcessStartInfo(Origin) { UseShellExecute = true }); }

    [STAThread]
    static int Main(string[] args)
    {
        headless = Array.IndexOf(args, "--verify-service") >= 0;
        Application.EnableVisualStyles();
        bool owner;
        using (var mutex = new Mutex(true, @"Local\ShasMaster.Reader", out owner))
        using (var reopen = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\ShasMaster.Open"))
        {
            if (!owner) { reopen.Set(); return 0; }
            NotifyIcon tray = null;
            StreamWriter log = null;
            SafeFileHandle job = null;
            try
            {
                job = CreateJobObject(IntPtr.Zero, null);
                var limits = new ExtendedLimits { Basic = new BasicLimits { Flags = 0x2000 } };
                if (job.IsInvalid || !SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(typeof(ExtendedLimits))))
                    throw new Exception("Windows could not prepare the reader process.");
                // Do not open an unrelated program listening on our port.
                var listener = new TcpListener(IPAddress.Loopback, Port);
                listener.Server.ExclusiveAddressUse = true;
                listener.Start(); listener.Stop();
                string root = AppDomain.CurrentDomain.BaseDirectory;
                string user = Environment.GetEnvironmentVariable("SHAS_USER_DATA") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Shas Master");
                Directory.CreateDirectory(user);
                string logPath = Path.Combine(user, "reader.log");
                object logLock = new object();
                log = new StreamWriter(logPath, true) { AutoFlush = true };
                Action<string> writeLog = line => {
                    if (line == null) return;
                    lock (logLock) {
                        if (log.BaseStream.Length > 1048576) {
                            log.Dispose();
                            string previous = Path.Combine(user, "reader.previous.log");
                            if (File.Exists(previous)) File.Delete(previous);
                            File.Move(logPath, previous);
                            log = new StreamWriter(logPath) { AutoFlush = true };
                        }
                        log.WriteLine(line);
                    }
                };
                var start = new ProcessStartInfo(Path.Combine(root, "shas-backend", "shas-backend.exe"), "--configuration Release") {
                    UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true,
                    WorkingDirectory = root
                };
                start.EnvironmentVariables["SHAS_CORPUS"] = Path.Combine(root, "prepared");
                start.EnvironmentVariables["SHAS_FRONTEND"] = Path.Combine(root, "dist");
                start.EnvironmentVariables["SHAS_USER_DATA"] = user;
                start.EnvironmentVariables["SHAS_PORT"] = Port.ToString();
                backend = new Process { StartInfo = start };
                backend.OutputDataReceived += (s, e) => writeLog(e.Data);
                backend.ErrorDataReceived += (s, e) => writeLog(e.Data);
                backend.Start(); started = true;
                if (!AssignProcessToJobObject(job, backend.Handle)) throw new Exception("Windows could not manage the reader process.");
                backend.BeginOutputReadLine(); backend.BeginErrorReadLine();
                DateTime deadline = DateTime.UtcNow.AddSeconds(120);
                bool ready = false;
                while (DateTime.UtcNow < deadline && !backend.HasExited) {
                    try {
                        var request = (HttpWebRequest)WebRequest.Create(Origin + "/api/session");
                        request.Timeout = 1000; request.Proxy = null;
                        using (var response = (HttpWebResponse)request.GetResponse()) ready = response.StatusCode == HttpStatusCode.OK;
                    } catch (WebException) { }
                    if (ready) break;
                    Thread.Sleep(100);
                }
                if (!ready || backend.HasExited) throw new Exception("The reader could not start. Details are in " + logPath);
                if (headless) {
                    while (!backend.HasExited) Thread.Sleep(100);
                    return backend.ExitCode == 0 ? 1 : backend.ExitCode;
                }
                var menu = new ContextMenuStrip();
                menu.Items.Add("Open Shas Master", null, (s, e) => OpenReader());
                menu.Items.Add("Quit Shas Master", null, (s, e) => Application.Exit());
                tray = new NotifyIcon { Icon = System.Drawing.SystemIcons.Application, Text = "Shas Master", ContextMenuStrip = menu, Visible = true };
                tray.DoubleClick += (s, e) => OpenReader();
                using (var timer = new System.Windows.Forms.Timer { Interval = 250 }) {
                    timer.Tick += (s, e) => {
                        if (backend.HasExited) { MessageBox.Show("The reader stopped. Open Shas Master again to continue.", "Shas Master"); Application.Exit(); }
                        else if (reopen.WaitOne(0)) OpenReader();
                    };
                    timer.Start(); OpenReader(); Application.Run();
                }
                return 0;
            }
            catch (Exception error) { if (!headless) MessageBox.Show(error.Message, "Shas Master could not open"); return 1; }
            finally {
                if (backend != null) {
                    if (started) { if (!backend.HasExited) backend.Kill(); backend.WaitForExit(); }
                    backend.Dispose();
                }
                if (tray != null) tray.Dispose();
                if (log != null) log.Dispose();
                if (job != null) job.Dispose();
                mutex.ReleaseMutex();
            }
        }
    }
}
