import vpype_cli

try:
    # Mimicking the call in dxf.py
    # Note: quoted paths might be the issue if interpreted literally by the parser inside execute
    # input path doesn't exist, but let's see if it parses usage
    vpype_cli.execute("read input.dxf linemerge linesort write output.dxf")
except Exception as e:
    print(f"Error: {e}")
