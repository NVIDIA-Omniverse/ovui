var Module = typeof Module !== "undefined" ? Module : {};

Module.print = function (text) {
  if (globalThis.ovuiAppendConsole) {
    globalThis.ovuiAppendConsole(text);
  } else {
    console.log(text);
  }
};

Module.printErr = function (text) {
  if (globalThis.ovuiAppendConsole) {
    globalThis.ovuiAppendConsole(text);
  } else {
    console.error(text);
  }
};
