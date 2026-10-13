# Bundled query stopwords

`en.txt` is the Snowball English list from `raw/snowball-tartarus.txt` in
[stopwords-iso/stopwords-en](https://github.com/stopwords-iso/stopwords-en/tree/ccc8898188850d8fb019d5f69c14a6635c3bd115).
`zh.txt` is `stopwords-zh.txt` from
[stopwords-iso/stopwords-zh](https://github.com/stopwords-iso/stopwords-zh/tree/0f62ec9b9061b9142ed87fa6b39d386945c7cf47).
Both are redistributed under the accompanying MIT license. The files retain their source content.

The analyzer applies these lists only to unquoted query words and explicitly retains negation words.
Document words and their frequencies are retained. Stopword updates do not change indexed tokens and require no index refresh.
Chinese segmentation uses Jieba 0.42.1's packaged dictionary in accurate mode with `HMM=False`.
