"""Run the saved entry and lazily observe unhandled exceptions using stdlib.

Before the program runs only sys/builtins are used, preserving local imports.
Projects replacing sys.excepthook stay in control; absent observations stay unknown.
"""

import sys


def main():
    kind, entry, path0, destination, *arguments = sys.argv[1:]
    original_hook = sys.excepthook
    helper = __file__
    helper_directory = helper[:max(helper.rfind('/'), helper.rfind('\\')) + 1]
    base = sys.base_prefix.replace('\\', '/').rstrip('/') + '/'

    def observe(exception_type, value, tb):
        while tb is not None and tb.tb_frame.f_code.co_filename == helper:
            tb = tb.tb_next
        BaseException.__traceback__.__set__(value, tb)
        if (type(value) not in (AttributeError, ImportError, ModuleNotFoundError, TypeError)
                or any(type(arg) not in (str, int, float, bool, bytes, type(None)) for arg in value.args)
                or value.__cause__ is not None or value.__context__ is not None):
            return original_hook(exception_type, value, tb)
        saved_path = sys.path[:]
        saved_modules = set(sys.modules)
        try:
            # A project can legitimately load its own json.py/re.py, etc. Never
            # replace those modules or invoke them solely to collect diagnostics.
            for name in getattr(sys, 'stdlib_module_names', ()):
                loaded = sys.modules.get(name)
                if type(loaded) is type(sys):
                    file = vars(loaded).get('__file__')
                    if type(file) is str and not file.replace('\\', '/').startswith(base):
                        return original_hook(exception_type, value, tb)
            # Helper imports must resolve from the interpreter, not project or
            # PYTHONPATH directories. Restore the path before calling the hook.
            sys.path[:] = [p for p in saved_path if type(p) is str
                           and p.replace('\\', '/').startswith(base)]
            loader = sys.modules['_frozen_importlib_external'].SourceFileLoader(
                '_fixfirst_native_evidence', helper_directory + '_runtime_evidence.py')
            runtime = type(sys)('_fixfirst_native_evidence')
            exec(loader.get_code(runtime.__name__), runtime.__dict__)
            import json
            import traceback
            inner = tb
            while inner is not None and inner.tb_next is not None:
                inner = inner.tb_next
            metadata = runtime.exception_metadata(value, tb)
            records = [
                {'type': 'failure', 'stage': 'run', 'nodeid': '',
                 'message': ''.join(traceback.format_exception(exception_type, value, tb)),
                 'record_source': 'native_exception'},
                {'type': 'exception', 'stage': 'run', 'nodeid': '',
                 'exception_type': exception_type.__name__, 'exception_module': exception_type.__module__,
                 'exception_message': str(value),
                 'source_file': inner.tb_frame.f_code.co_filename if inner else '',
                 'source_line': inner.tb_lineno if inner else None,
                 'record_source': 'native_exception', **metadata},
            ]
            text = '\n'.join(json.dumps(r, ensure_ascii=True) for r in records) + '\n'
            if len(text.encode('utf-8')) <= 800_000:
                with open(destination, 'w', encoding='utf-8') as stream:
                    stream.write(text)
        except BaseException:
            pass  # Recording must never replace the original exception.
        finally:
            sys.path[:] = saved_path
            for name in set(sys.modules) - saved_modules:
                sys.modules.pop(name, None)
        original_hook(exception_type, value, tb)

    sys.excepthook = observe
    sys.argv[:] = [entry, *arguments]
    sys.orig_argv = [sys.executable, *(['-m', entry] if kind == 'module' else [entry]), *arguments]
    sys.path[0] = path0
    module = type(sys)('__main__')
    sys.modules['__main__'] = module
    if kind == 'module':
        import runpy
        runpy._run_module_as_main(entry, alter_argv=True)
    else:
        loader_type = sys.modules['_frozen_importlib_external'].SourceFileLoader
        module.__dict__.update(__file__=entry, __package__=None, __cached__=None,
                               __loader__=loader_type('__main__', entry))
        with open(entry, 'rb') as stream:
            code = compile(stream.read(), entry, 'exec')
        exec(code, module.__dict__)


if __name__ == '__main__':
    main()
