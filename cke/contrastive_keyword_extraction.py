import string
import nltk
from tqdm import trange
from .sentence_importance import *
from .sentence_comparision import *
import pysbd
from collections import Counter
from .utilities import * 
import numpy as np

def final_score(documents, changed_indices, new_indices, matched_dict, ranking, max_ngram,
                additions, removed_indices, deleted, combinator=alpha_combination, 
                top_k=0, alpha_gamma=0.5, min_ngram = 1,
                symbols_to_remove=string.punctuation, extra_stopwords=[], num_keywords=10):
    
    # init Sentence Boundary Detector
    seg = pysbd.Segmenter(language="en", clean=False)

    # tokenize document into sentencs
    sentences_a = seg.segment(documents[0]) 
    
    # tokenize document into sentencs
    sentences_b = seg.segment(documents[-1]) 

    doc_level_stats = build_doc_level_freqs(documents, maxngram=max_ngram, extra_stopwords=extra_stopwords)

    # Importance of sentences for current document
    I_sprev = ranking[0]
    I_s = ranking[1]
    
    former_contrastiveness, latter_contrastiveness = contrastive_importance(documents[0], documents[-1])

    # computed intermediate Keywords for contrastive KE between the current and prev Document Version    
    keywords = {}
    
    former_keywords = {}

    latter_keywords = {}


    # loop over the changed sentences
    for i in list(set(changed_indices)):
        for k in range(len(matched_dict[i])):
            # extract the correspdoning matched sentence
            matched_idx, score = matched_dict[i][k]
            
            # Calculate the Importance of the change that led to new sentence
            # Hypothesis 1: Importance of previous Sentence times semantic similarity
            # of changed and matched sentence
            I_ci = I_sprev[i] * score

            # Retrieve the Importance of the matched sentence
            I_si = I_s[int(matched_idx)] 
            
            # Combine the two scores using a combinator
            s_c = combinator(I_ci, I_si, alpha_gamma)

            current_adds = additions[i].get(int(matched_idx), [])
            current_freqs = build_diff_level_freqs(current_adds, symbols_to_remove, extra_stopwords)
            # loop over all ngrams/freqs in the sentence
            
            for ngram, freq in current_freqs.items():
                # ratio := fl / fe 
                # fe ... frequency of ngram in earlier version
                # fl ... frequency of ngram in latter version
                ratio = float(doc_level_stats[1].get(ngram, 0)) / float(doc_level_stats[0].get(ngram, 1))

                # include added ngrams, scored by their frequency * score of the change 
                keywords[ngram] = keywords.get(ngram, 0) + float(ratio * np.log(freq + 0.001) * s_c)
                latter_keywords[ngram] = latter_keywords.get(ngram, 0) + float(ratio * np.log(freq + 0.001) * s_c)
                
        # get frequencies of sentence in older version
        # in order to include deletions as keywords
        # incase of presence of splits: deleted = unified_diff
        current_deletions = deleted[i]
        old_freqs = build_diff_level_freqs(current_deletions, symbols_to_remove, extra_stopwords)

        # loop over all ngrams/freqs in the sentence
        for ngram, freq in old_freqs.items():
            # ratio := fe / fl
            # fe ... frequency of ngram in earlier version
            # fl ... frequency of ngram in latter version
            ratio = doc_level_stats[0].get(ngram, 0) / doc_level_stats[1].get(ngram, 1)
            
            # include deleted ngrams, scored by their frequency * score of the change
            keywords[ngram] = keywords.get(ngram, 0) + float(ratio * np.log(freq + 0.001)  * s_c)
            former_keywords[ngram] = former_keywords.get(ngram, 0) + float(ratio * np.log(freq + 0.001)  * s_c)

    # newly added sentence: ( new := has not been matched to)
    for i in new_indices:
        
        # Compute the Dictonary of frequency for all ngrams up to "max_ngram" in new sentence
        current_freqs = build_sentence_freqs_max_ngram(sentences_b[i], 
                                                       higher_ngram=max_ngram, lower_ngram=min_ngram,
                                                       symbols_to_remove=symbols_to_remove,
                                                       extra_stopwords=extra_stopwords)
        
        
        for ngram, freq in current_freqs.items():
            
            ratio = float(doc_level_stats[1].get(ngram, 1)) / float(doc_level_stats[0].get(ngram, 1))
            
            # include added ngrams, scored by their frequency * Importance of the sentence
            keywords[ngram] = keywords.get(ngram, 0) + float(freq * latter_contrastiveness[i] * ratio)
            latter_keywords[ngram] = latter_keywords.get(ngram, 0) + float(freq * latter_contrastiveness[i] * ratio)
            
    
    # removed sentence: ( removed := no match found)
    for i in removed_indices:
        
        # Compute the Dictonary of frequency for all ngrams up to "max_ngram" in deleted sentence
        current_freqs = build_sentence_freqs_max_ngram(sentences_a[i], 
                                                       higher_ngram=max_ngram, lower_ngram=min_ngram,
                                                       symbols_to_remove=symbols_to_remove,
                                                       extra_stopwords=extra_stopwords)
        
        
        for ngram, freq in current_freqs.items():
            
            ratio = float(doc_level_stats[0].get(ngram, 1)) / float(doc_level_stats[1].get(ngram, 1))

            # include deleted ngrams, scored by their frequency * Importance of the sentence
            keywords[ngram] = keywords.get(ngram, 0) + float(ratio * freq * former_contrastiveness[i])
            former_keywords[ngram] = former_keywords.get(ngram, 0) + float(ratio * freq * former_contrastiveness[i])

    # normalize keywords
    # total "IMPORTANCE COUNT

    keywords = {k: float(v)  for k, v in sorted(keywords.items(), key=lambda item: item[1], 
                                                 reverse=True)}
    

    former_keywords = {k: float(v)  for k, v in sorted(former_keywords.items(), key=lambda item: item[1], 
                                                 reverse=True)}
    
    latter_keywords = {k: float(v)  for k, v in sorted(latter_keywords.items(), key=lambda item: item[1], 
                                                 reverse=True)}


    # sort keywords + normalize
    keywords = normalize_keywords(keywords, num_keywords)


    former_keywords = normalize_keywords(former_keywords, num_keywords)
    
    latter_keywords = normalize_keywords(latter_keywords, num_keywords)
    
    return keywords, former_keywords, latter_keywords





def extract_contrastive_keywords(document_a, document_b, max_ngram=2, min_ngram=1, 
                           importance_estimator= text_rank_importance,
                           combinator=alpha_combination, threshold=0.6, num_splits=1, alpha_gamma=0.5, 
                           matching_model='all-MiniLM-L6-v2', 
                           match_sentences =match_sentences_semantic_search, show_changes=False,
                           symbols_to_remove=[","], extra_stopwords=[], num_keywords=10):
    
    
    documents = [document_a, document_b]
    # rank all sentences in their respective version
    # available esitmators: text_rank_importance, yake_weighted_importance, yake_unweighted_importance 
    ranking = importance_estimator(documents)
    
    # Perform Matching
    # matchers: semantic_search, weighted_tfidf
    matched_dict, removed = match_sentences(documents[0], documents[-1],threshold, num_splits, matching_model)
    
    
    # determine WHAT has changed
    # Using Myers algorithm
    changed_indices, new_indices, additions, deletions, matched_indices, unified_delitions = detect_changes(matched_dict, documents[0], documents[-1], 
                                        max_ngram=max_ngram, show_output=show_changes,
                                        symbols_to_remove=symbols_to_remove, top_k=num_splits,
                                        extra_stopwords=extra_stopwords)
    
    

    # extract keywords
    keywords, former_keywords, latter_keywords = final_score(documents, changed_indices, new_indices, matched_dict, 
                                        ranking, max_ngram, additions, removed,
                                        unified_delitions, combinator, 
                                        alpha_gamma=alpha_gamma, min_ngram= min_ngram, 
                                        symbols_to_remove=symbols_to_remove,
                                        extra_stopwords=extra_stopwords,
                                        num_keywords=num_keywords)
    
    
    return keywords, former_keywords, latter_keywords


