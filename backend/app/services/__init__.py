"""Services behind the workspace endpoints: code intelligence over a run's generated files.

`codebase_index` builds a file/symbol/reference index, `change_impact` turns a proposed change
into the files it touches and what would break, and `workspace_manager` applies bounded patches
while keeping `index.html` the source of truth the rest of the pipeline publishes from.
"""
