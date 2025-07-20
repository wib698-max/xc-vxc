from flask import Flask, request, jsonify
import pandas as pd
from langdetect import detect
from transformers import MarianMTModel, MarianTokenizer
import os

app = Flask(__name__)

# Global variables
french_to_shimarore = {}
shimarore_to_french = {}
models = {}

def load_model_and_tokenizer(model_path):
    """Load model and tokenizer from local directory"""
    try:
        tokenizer = MarianTokenizer.from_pretrained(model_path)
        model = MarianMTModel.from_pretrained(model_path)
        return tokenizer, model
    except Exception as e:
        print(f"Error loading model from {model_path}: {e}")
        return None, None

def initialize_app():
    """Initialize dictionaries and models"""
    global french_to_shimarore, shimarore_to_french, models
    
    try:
        # Load dataset
        df = pd.read_csv("data (1).csv")
        french_to_shimarore = dict(zip(df['text'].str.lower(), df['target'].str.lower()))
        shimarore_to_french = dict(zip(df['target'].str.lower(), df['text'].str.lower()))
        
        print("Dictionary loaded successfully!")
        
        # Load models
        print("Loading translation models...")
        models['fr_en_tokenizer'], models['fr_en_model'] = load_model_and_tokenizer("fine_tuned_fr_en_model")
        models['en_fr_tokenizer'], models['en_fr_model'] = load_model_and_tokenizer("fine_tuned_en_fr_model")
        models['sw_en_tokenizer'], models['sw_en_model'] = load_model_and_tokenizer("fine_tuned_sw_en_model")
        models['en_sw_tokenizer'], models['en_sw_model'] = load_model_and_tokenizer("fine_tuned_en_sw_model")
        
        print("All models loaded successfully!")
        
    except Exception as e:
        print(f"Error during initialization: {e}")

def replace_words_with_mapping(text, mapping_dict):
    """Replace words using provided mapping dictionary"""
    words = text.lower().split()
    replaced_words = []
    replaced = False
    
    for word in words:
        if word in mapping_dict:
            replaced_words.append(mapping_dict[word])
            replaced = True
        else:
            replaced_words.append(word)
    
    return ' '.join(replaced_words), replaced

def translate_text(text, tokenizer, model):
    """Translate text using provided model"""
    try:
        inputs = tokenizer(text, return_tensors="pt", padding=True, truncation=True)
        translated = model.generate(**inputs)
        return tokenizer.decode(translated[0], skip_special_tokens=True)
    except Exception as e:
        return f"Translation error: {str(e)}"

def detect_language_smart(text):
    """Smart language detection with fallbacks"""
    try:
        detected = detect(text)
        return detected
    except:
        # Fallback: check if words exist in our dictionaries
        words = text.lower().split()
        french_matches = sum(1 for word in words if word in french_to_shimarore)
        shimarore_matches = sum(1 for word in words if word in shimarore_to_french)
        
        if french_matches > shimarore_matches:
            return "fr"
        elif shimarore_matches > french_matches:
            return "sw"
        else:
            return "unknown"

@app.route('/')
def home():
    return jsonify({
        "message": "Unified French-Shimarore Translation API",
        "usage": "POST to /translate with {'text': 'your text'} or {'texts': ['text1', 'text2']}",
        "features": [
            "Single word direct mapping",
            "Full sentence translation",
            "Batch translation",
            "Auto language detection",
            "Bidirectional translation (French ↔ Shimarore)"
        ]
    })

@app.route('/translate', methods=['POST'])
def translate():
    """Unified translation endpoint - handles everything"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        # Handle both single text and batch requests
        if 'text' in data:
            # Single text translation
            result = process_single_translation(data['text'])
            return jsonify(result)
        
        elif 'texts' in data:
            # Batch translation
            if not isinstance(data['texts'], list):
                return jsonify({"error": "'texts' must be a list"}), 400
            
            results = []
            for text in data['texts']:
                result = process_single_translation(text)
                results.append(result)
            
            return jsonify({
                "batch_translation": True,
                "total_processed": len(results),
                "results": results
            })
        
        else:
            return jsonify({
                "error": "Provide either 'text' for single translation or 'texts' for batch translation"
            }), 400
    
    except Exception as e:
        return jsonify({"error": f"Translation failed: {str(e)}"}), 500

def process_single_translation(text):
    """Process a single text translation"""
    try:
        if not text or not text.strip():
            return {"error": "Empty text provided"}
        
        original_text = text.strip()
        sentence = text.strip().lower()
        
        # SINGLE WORD HANDLING
        if len(sentence.split()) == 1:
            # Direct mapping lookup
            if sentence in french_to_shimarore:
                return {
                    "input": original_text,
                    "output": french_to_shimarore[sentence],
                    "translation_type": "direct_mapping",
                    "source_language": "french",
                    "target_language": "shimarore",
                    "method": "dictionary_lookup"
                }
            
            elif sentence in shimarore_to_french:
                return {
                    "input": original_text,
                    "output": shimarore_to_french[sentence],
                    "translation_type": "direct_mapping", 
                    "source_language": "shimarore",
                    "target_language": "french",
                    "method": "dictionary_lookup"
                }
            
            else:
                return {
                    "input": original_text,
                    "output": None,
                    "translation_type": "single_word_not_found",
                    "error": "Word not found in dictionary",
                    "suggestion": "Try using the word in a complete sentence for AI translation"
                }
        
        # FULL SENTENCE HANDLING
        else:
            detected_lang = detect_language_smart(sentence)
            
            if detected_lang == "fr":
                # French to Shimarore
                return translate_french_to_shimarore(original_text, sentence)
            
            elif detected_lang == "sw":
                # Shimarore to French  
                return translate_shimarore_to_french(original_text, sentence)
            
            else:
                return {
                    "input": original_text,
                    "output": None,
                    "detected_language": detected_lang,
                    "error": "Language not supported or could not be detected",
                    "supported_languages": ["French (fr)", "Shimarore/Swahili (sw)"]
                }
    
    except Exception as e:
        return {"error": f"Processing failed: {str(e)}"}

def translate_french_to_shimarore(original_text, sentence):
    """Translate French text to Shimarore"""
    try:
        # Step 1: Replace French words with Shimarore equivalents
        processed_sentence, words_replaced = replace_words_with_mapping(sentence, french_to_shimarore)
        
        # Step 2: Translate via English
        if models['fr_en_tokenizer'] and models['en_sw_tokenizer']:
            english_text = translate_text(processed_sentence, models['fr_en_tokenizer'], models['fr_en_model'])
            shimarore_text = translate_text(english_text, models['en_sw_tokenizer'], models['en_sw_model'])
            
            return {
                "input": original_text,
                "output": shimarore_text,
                "translation_type": "full_sentence",
                "source_language": "french",
                "target_language": "shimarore",
                "method": "dictionary_preprocessing + ai_translation",
                "processing_steps": {
                    "1_original": sentence,
                    "2_after_dictionary": processed_sentence,
                    "3_intermediate_english": english_text,
                    "4_final_shimarore": shimarore_text
                },
                "words_replaced_from_dictionary": words_replaced
            }
        else:
            return {"error": "French to Shimarore translation models not available"}
    
    except Exception as e:
        return {"error": f"French to Shimarore translation failed: {str(e)}"}

def translate_shimarore_to_french(original_text, sentence):
    """Translate Shimarore text to French"""
    try:
        # Step 1: Replace Shimarore words with French equivalents
        processed_sentence, words_replaced = replace_words_with_mapping(sentence, shimarore_to_french)
        
        # Step 2: Translate via English
        if models['sw_en_tokenizer'] and models['en_fr_tokenizer']:
            english_text = translate_text(processed_sentence, models['sw_en_tokenizer'], models['sw_en_model'])
            french_text = translate_text(english_text, models['en_fr_tokenizer'], models['en_fr_model'])
            
            return {
                "input": original_text,
                "output": french_text,
                "translation_type": "full_sentence",
                "source_language": "shimarore",
                "target_language": "french", 
                "method": "dictionary_preprocessing + ai_translation",
                "processing_steps": {
                    "1_original": sentence,
                    "2_after_dictionary": processed_sentence,
                    "3_intermediate_english": english_text,
                    "4_final_french": french_text
                },
                "words_replaced_from_dictionary": words_replaced
            }
        else:
            return {"error": "Shimarore to French translation models not available"}
    
    except Exception as e:
        return {"error": f"Shimarore to French translation failed: {str(e)}"}

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "dictionary_entries": {
            "french_to_shimarore": len(french_to_shimarore),
            "shimarore_to_french": len(shimarore_to_french)
        },
        "models_loaded": {
            "fr_en": models.get('fr_en_model') is not None,
            "en_fr": models.get('en_fr_model') is not None, 
            "sw_en": models.get('sw_en_model') is not None,
            "en_sw": models.get('en_sw_model') is not None
        }
    })

if __name__ == '__main__':
    initialize_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
