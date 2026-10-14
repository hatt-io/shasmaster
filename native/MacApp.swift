import AppKit
import WebKit
import Foundation
import Darwin

final class ReaderApp: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    let service = Process()
    let headless = CommandLine.arguments.contains("--verify-service")
    let port = Int(ProcessInfo.processInfo.environment["SHAS_PORT"] ?? "9473") ?? 9473
    var window: NSWindow?
    var readyTimer: Timer?
    var quitting = false
    var deadline = Date().addingTimeInterval(120)
    var origin: URL { URL(string: "http://127.0.0.1:\(port)")! }

    func applicationDidFinishLaunching(_ notification: Notification) {
        do { try startService() } catch { fail(error.localizedDescription) }
    }

    func startService() throws {
        // Never accidentally open a different program that owns our local port.
        let socketFD = socket(AF_INET, SOCK_STREAM, 0)
        guard socketFD >= 0 else { throw NSError(domain: "Reader", code: 1, userInfo: [NSLocalizedDescriptionKey:"Cannot start the reader connection."]) }
        var reuse: Int32 = 1
        setsockopt(socketFD, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = UInt16(port).bigEndian
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(socketFD, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        close(socketFD)
        guard bound == 0 else { throw NSError(domain:"Reader",code:2,userInfo:[NSLocalizedDescriptionKey:"Shas Master is already running, or another program is using its connection. Close the other reader and open this app again."]) }

        let resources = Bundle.main.resourceURL!
        var environment = ProcessInfo.processInfo.environment
        let user = environment["SHAS_USER_DATA"].map { URL(fileURLWithPath:$0) }
            ?? FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Shas Master")
        try FileManager.default.createDirectory(at:user,withIntermediateDirectories:true)
        let logURL = user.appendingPathComponent("reader.log")
        if let size = try? logURL.resourceValues(forKeys:[.fileSizeKey]).fileSize, size > 1_048_576 {
            let previous = user.appendingPathComponent("reader.previous.log")
            try? FileManager.default.removeItem(at:previous)
            try FileManager.default.moveItem(at:logURL,to:previous)
        }
        if !FileManager.default.fileExists(atPath:logURL.path) { FileManager.default.createFile(atPath:logURL.path,contents:nil) }
        let log = try FileHandle(forWritingTo:logURL)
        try log.seekToEnd()
        environment["SHAS_USER_DATA"] = user.path
        environment["SHAS_CORPUS"] = resources.appendingPathComponent("prepared").path
        environment["SHAS_FRONTEND"] = resources.appendingPathComponent("dist").path
        environment["SHAS_PORT"] = String(port)
        environment["NODE_ENV"] = "production"
        service.executableURL = resources.appendingPathComponent("shas-backend/shas-backend")
        service.arguments = ["--configuration","Release"]
        service.environment = environment
        service.standardOutput = log
        service.standardError = log
        service.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self = self, !self.quitting else { return }
                self.fail("The reader stopped. Your saved work is kept separately. Details are in \(logURL.path).")
            }
        }
        try service.run()
        try log.close()
        readyTimer = Timer.scheduledTimer(withTimeInterval:0.15,repeats:true) { [weak self] _ in self?.checkReady() }
    }

    func checkReady() {
        if Date() > deadline { fail("The reader could not start. Close the app and try again."); return }
        var request = URLRequest(url:origin.appendingPathComponent("api/session"))
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with:request) { [weak self] _, response, _ in
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { return }
            DispatchQueue.main.async {
                guard let self = self, self.readyTimer != nil, self.service.isRunning else { return }
                self.readyTimer?.invalidate(); self.readyTimer = nil
                if self.headless { print("Reader service ready"); fflush(stdout) }
                else { self.showReader() }
            }
        }.resume()
    }

    func showReader() {
        let browser = WKWebView(frame:.zero)
        browser.navigationDelegate = self
        let window = NSWindow(contentRect:NSRect(x:0,y:0,width:1300,height:950),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        window.title = "Shas Master"
        window.contentView = browser
        window.center()
        window.makeKeyAndOrderFront(nil)
        self.window = window
        browser.load(URLRequest(url:origin))
        NSApp.activate(ignoringOtherApps:true)
    }

    func webView(_ webView:WKWebView, decidePolicyFor navigationAction:WKNavigationAction, decisionHandler:@escaping (WKNavigationActionPolicy)->Void) {
        let url = navigationAction.request.url
        decisionHandler(url?.host == "127.0.0.1" && url?.port == port && url?.scheme == "http" ? .allow : .cancel)
    }

    func fail(_ message:String) {
        guard !quitting else { return }
        if headless { fputs(message+"\n",stderr) }
        else { let alert=NSAlert(); alert.messageText="Shas Master could not open"; alert.informativeText=message; alert.runModal() }
        stopService()
        exit(1)
    }

    func stopService() {
        quitting = true
        readyTimer?.invalidate(); readyTimer=nil
        if service.isRunning { service.terminate(); service.waitUntilExit() }
    }
    func applicationWillTerminate(_ notification:Notification) { stopService() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender:NSApplication)->Bool { true }
}

let delegate = ReaderApp()
let application = NSApplication.shared
application.delegate = delegate
application.setActivationPolicy(delegate.headless ? .prohibited : .regular)
let menu = NSMenu()
let appItem = NSMenuItem(); let appMenu = NSMenu()
appMenu.addItem(withTitle:"Quit Shas Master",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
appItem.submenu=appMenu; menu.addItem(appItem)
let editItem=NSMenuItem(); editItem.title="Edit"; let editMenu=NSMenu(title:"Edit")
for (title,selector,key) in [("Undo","undo:","z"),("Cut","cut:","x"),("Copy","copy:","c"),("Paste","paste:","v"),("Select All","selectAll:","a")] {
    editMenu.addItem(withTitle:title,action:NSSelectorFromString(selector),keyEquivalent:key)
}
editItem.submenu=editMenu; menu.addItem(editItem); application.mainMenu=menu
signal(SIGTERM,SIG_IGN); signal(SIGINT,SIG_IGN)
let term=DispatchSource.makeSignalSource(signal:SIGTERM,queue:.main)
term.setEventHandler { application.terminate(nil) }; term.resume()
let interrupt=DispatchSource.makeSignalSource(signal:SIGINT,queue:.main)
interrupt.setEventHandler { application.terminate(nil) }; interrupt.resume()
application.run()
