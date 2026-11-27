- The client keeps upstream's answers in core's response cache for 300 seconds, every
  path: a second call of a task within that time sends no request, and its
  `meta.retrieved_at` is the time the first answer was stored. A file that
  `download_release_file` streams is never kept. (sdk-core ADR-0061,
  https://github.com/xippios/sdk-core/issues/479)
