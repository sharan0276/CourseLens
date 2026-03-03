import os
import glob
import json
from services.ingestion.ppt_parser import PPTXParser
from services.ingestion.cleaner import SlideCleaner
from services.chunking.chunk_builder import ChunkBuilder
from services.embedding.embedder import Embedder
from db.vector_store import VectorStore
from services.ingestion.emf_to_png import convert_all_emfs_in_directory
from services.ingestion.pdf_parser import PDFParser

class IngestionService:
    """
    Responsible for orchestrating the ingestion process.
    """
    def __init__(self, db_path: str = "./courselens_db"):
        self.pptx_parser = PPTXParser(image_folder_path="CourseLens_data/images")
        self.pdf_parser = PDFParser(image_folder_path="CourseLens_data/images")
        self.slide_cleaner = SlideCleaner()
        self.chunk_builder = ChunkBuilder()
        self.embedding_service = Embedder()
        self.vector_store = VectorStore(db_path)
        os.makedirs("CourseLens_data/processed_data", exist_ok=True)
        os.makedirs("CourseLens_data/images", exist_ok=True)


    def ingest_folder(self, folder_path: str):
        """
        Orchestrates full ingestion for a folder (PPTX + PDF)
        """

        print("Processing PPTX files...")
        pptx_metrics = self.ingest_folder_pptx(folder_path)

        print("Processing PDF files...")
        pdf_metrics = self.ingest_folder_pdf(folder_path)

        # Combined metrics
        return {
                "pptx_files_processed": pptx_metrics["files_processed"],
                "total_extracted_slides": pptx_metrics["total_extractedslides"],
                "pdf_files_processed": pdf_metrics["pdf_files_processed"],
                "total_extracted_pages": pdf_metrics["total_extracted_sections"],
                "total_files_processed": (
                    pptx_metrics["files_processed"] + 
                    pdf_metrics["pdf_files_processed"]
                )
        }


    def ingest_folder_pptx(self, folder_path: str):
        """
        Orchestrates the ingestion process for a folder of PPTX files.
        """

        files_processed = 0
        total_slides = 0

        for filepath in glob.glob(os.path.join(folder_path, "*.pptx")):
            try:
                slides = self.pptx_parser.parse(filepath)
                cleaned_slides = [self.slide_cleaner.clean(slide) for slide in slides]
                output_file = os.path.join("CourseLens_data/processed_data", os.path.basename(filepath).replace(".pptx", ".json"))
                output_data = {
                    "source_file" : os.path.basename(filepath),
                    "total_slides" : len(cleaned_slides),
                    "slides" : [slide.to_dict() for slide in cleaned_slides]
                }
                with open(output_file, "w") as f:
                    json.dump(output_data, f, indent=4)
                files_processed += 1
                total_slides += len(cleaned_slides)
            
            except Exception as e:
                print(f"Error processing {filepath}: {str(e)}")

        # Convert all EMF images to PNG
        
        # All PPTX files are processed, now convert all EMF images to PNG
        convert_all_emfs_in_directory("CourseLens_data/images")

        return {
            "files_processed" : files_processed,
            "total_extractedslides" : total_slides
        }

    def ingest_folder_pdf(self, folder_path: str):
        """
        Handles ingestion of all pdf files in the folder locationm
        Deetct orientation internally and calls appropriate functions
        """
        files_processed = 0
        total_sections = 0

        for filepath in glob.glob(os.path.join(folder_path, "*.pdf")):
            try:
                slides = self.pdf_parser.parse_pdf(filepath)
                cleaned_slides = [ self.slide_cleaner.clean(slide) for slide in slides]
                output_file = os.path.join("CourseLens_data/processed_data", os.path.basename(filepath).replace(".pdf", ".json"))
                output_data = {
                    "source_file": os.path.basename(filepath),
                    "total_slides": len(cleaned_slides),
                    "slides" : [slide.to_dict() for slide in cleaned_slides]
                }
                with open(output_file, "w") as f:
                    json.dump(output_data, f, indent = 4)
                
                files_processed += 1

                total_sections += len(cleaned_slides)

            except Exception as e : 
                print(f"Error processing {filepath}: {str(e)}")
            
        return {
            "pdf_files_processed": files_processed,
            "total_extracted_sections": total_sections
        }

    def create_embeddings_for_file(self, json_path: str):
        """
            Creates embeddings for a single JSON file.
        """
        print(f"\nProcessing: {json_path}")

        # Step 1: Build Chunks
        parent_chunks, child_chunks = self.chunk_builder.build_from_json(json_path)
        print(f"Built {len(parent_chunks)} parent chunks and {len(child_chunks)} child chunks")

        print("\n--- Sample Parent Chunk ---")
        if parent_chunks:
            p = parent_chunks[1]
            print(f"ID       : {p['id']}")
            print(f"Title    : {p['metadata']['title']}")
            print(f"Children : {p['metadata']['child_ids']}")
            print(f"Text preview:\n{p['text'][:800]}...")

        # inspect first child chunk
        print("\n--- Sample Child Chunk ---")
        if child_chunks:
            c = child_chunks[0]
            print(f"ID          : {c['id']}")
            print(f"Title       : {c['metadata']['title']}")
            print(f"Slide num   : {c['metadata']['slide_number']}")
            print(f"Parent ID   : {c['metadata']['parent_id']}")
            print(f"Prev slide  : {c['metadata']['prev_slide']}")
            print(f"Next slide  : {c['metadata']['next_slide']}")
            print(f"Only images : {c['metadata']['only_images']}")
            print(f"Text preview:\n{c['text'][:400]}...")

            
        # check navigation links
        print("\n--- Navigation Link Check ---")
        first = child_chunks[0]
        last = child_chunks[-1]
        print(f"First slide prev_slide : {first['metadata']['prev_slide']}")
        print(f"Last slide next_slide  : {last['metadata']['next_slide']}")
        print(f"Middle slide links     : prev={child_chunks[5]['metadata']['prev_slide']} next={child_chunks[5]['metadata']['next_slide']}")

        # check image only slides
        image_only = [c for c in child_chunks if c['metadata']['only_images']]
        print(f"\nImage only slides: {len(image_only)}")
        if image_only:
            print(f"Sample: {image_only[0]['id']} — context_strategy: {image_only[0]['metadata'].get('context_strategy', 'NOT SET')}")

        # Step 2: Embed Chunks
        parent_chunks = self.embedding_service.embed_chunks(parent_chunks)
        child_chunks = self.embedding_service.embed_chunks(child_chunks)
        print("Embeddings created for all chunks")

        print("\n--- Sample Embedded Chunk ---")
        if child_chunks:
            c = child_chunks[0]
            print(f"ID          : {c['id']}")
            print(f"Embedding   : {c['embedding'][:4]}... (first 4 values)")
            print(f"Vector dim  : {len(c['embedding'])}")

        parent_emb_dim = set([len(p['embedding']) for p in parent_chunks])
        child_emb_dim = set([len(c['embedding']) for c in child_chunks])

        if len(parent_emb_dim) ==  1 or len(child_emb_dim) == 1:
            print("Embeddings Dimesion are consistent!")
        else:
                print("Embeddings Dimesion are not consistent!")


        print(f"\nParent embedding dimensions: {parent_emb_dim}")
        print(f"Child embedding dimensions: {child_emb_dim}")

        # Step 3 - Store in Vector DB
        print("\nStoring Parent Chunks in Vector DB...")
        self.vector_store.store(parent_chunks)
        print("\nStoring Child Chunks in Vector DB...")
        self.vector_store.store(child_chunks)
        print("Chunks stored in Vector DB")
            
        print(f"Embeding complete for {json_path}")

        
    def create_embeddings_for_folder(self, folder_path: str):
        """
        Creates embeddings for all JSON files in a folder.
        """
        for json_path in glob.glob(os.path.join(folder_path, "*.json")):
            self.create_embeddings_for_file(json_path)
            
        print("\nEmbeding complete for all files")