# Extracts images from PPTX files and saves them to image folder.
import os
from pptx.enum.shapes import MSO_SHAPE_TYPE

class ImageExtractor:
    """
    Responsible for extracting images from PPTX files and saving them to image folder.
    Handles only EMBEDDED_OLE_OBJECT type of shapes because those have a flowchart based diagrams from initial assessment.
    """
    def __init__(self, image_folder_path: str):
        self.image_folder_path = image_folder_path
        os.makedirs(self.image_folder_path, exist_ok=True)

    
    def extract(self, slide, slide_number: int, filepath: str) -> list:
        """
        Iterates all shapes on a slide and extracts any OLE shape found.
        Returns a list of images extracted from the slide.
        """

        images = []
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT:
                self._extract_ole_object(shape, slide_number, filepath, images)
            elif shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                self._extract_picture(shape, slide_number, filepath, images)
        return images


    def _extract_picture(self, shape, slide_number: int, filepath: str, images: list):
        """
        Extracts the preview images from a picture shape
        shape.image gives direct access to image blob
        Saved the final image at .png using shape_id
        """

        try:
            image = shape.image
            base = os.path.basename(filepath).replace('.pptx', '')
            image_filename = f"{base}_slide_{slide_number}_image_{shape.shape_id}.png"
            image_path = os.path.join(self.image_folder_path, image_filename)
            with open(image_path, "wb") as f:
                f.write(image.blob)
            images.append({
                "filename" : image_filename,
                "slide_number" : slide_number,
            })
            print(f"Successfully extracted image from slide {slide_number}")
        except Exception as e:
            print(f"Error extracting image from slide {slide_number}: {str(e)}")

    
    def _extract_ole_object(self, shape, slide_number: int, filepath: str, images: list):
        """
        Extracts the preview images from an OLE object

        OLE objects are wrapped in a GraphicFrame container so shape.image is not directly accessible. 
        Hence we need to access the XML relationships and extract the imaghe from relationship that mentions image.

        Saved as .emf (Enhances Metafile Foirmat) since it is the format used by PowerPoint.
        """

        try:
            for rel in shape.part.rels.values():
                if "image" in rel.reltype:
                    image_blob = rel.target_part.blob
                    image_filename = f"{os.path.basename(filepath).replace('.pptx', '')}_slide_{slide_number}_image_{shape.shape_id}.emf"
                    image_path = os.path.join(self.image_folder_path, image_filename)
                    with open(image_path, "wb") as f:
                        f.write(image_blob)
                        
                    images.append({
                        "filename" : image_filename,
                        "slide_number" : slide_number,
                    })
                    print(f"Successfully extracted image from slide {slide_number}")
                    break 
        except Exception as e:
            print(f"Error extracting image from slide {slide_number}: {str(e)}")
